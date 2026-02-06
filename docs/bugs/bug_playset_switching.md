# Bug Report: QBuilder Fails on Playset Switch

**Severity:** High  
**Component:** qbuilder/ipc_server.py, qbuilder/cli.py  
**Date:** 2026-02-06

---

## Summary

When switching playsets via the MCP tool `ck3_playset(command="switch")`, the qbuilder daemon may fail to properly rebuild the database for the new playset. The issue stems from inconsistent playset file resolution between different code paths.

## Symptoms

1. User switches playset via `ck3_playset(command="switch", name="New Playset")`
2. Daemon receives `enqueue_scan` IPC command
3. Daemon may fail to find playset file or may use stale playset reference
4. Build queue remains empty or processes wrong files

## Root Cause Analysis

### Multiple Playset Resolution Paths

The codebase has multiple ways to resolve the active playset:

| Location | Resolution Method |
|----------|-------------------|
| `cli.py` fresh reset | Uses `get_active_playset_file()` - looks for `~/.ck3raven/active_playset.json` |
| `ipc_server.py` enqueue_scan | Looks at `qbuilder/../playsets/playset_manifest.json` |
| MCP tools | May use different config sources |

This inconsistency means different parts of the system may disagree about which playset is active.

### Code Evidence

In `ipc_server.py` `_handle_enqueue_scan()` (lines 350-367):
```python
# Uses repo-relative path:
playsets_dir = Path(__file__).parent.parent / 'playsets'
manifest_path = playsets_dir / 'playset_manifest.json'
```

But `cli.py` and other parts likely use:
```python
# Uses user config:
from ck3raven.db.playsets import get_active_playset_file
playset_path = get_active_playset_file()  # ~/.ck3raven/...
```

## Recommended Fix

### Option A: Unified Resolution Function

Create a single authoritative function for resolving active playset:

```python
# In qbuilder/config.py or similar
def get_active_playset_path() -> Optional[Path]:
    """Single source of truth for active playset."""
    # 1. Check IPC request param (explicit override)
    # 2. Check ~/.ck3raven/active_playset.json (user config)
    # 3. Check playsets/playset_manifest.json (legacy fallback)
    pass
```

Then use this everywhere:
- `cli.py` `cmd_daemon`
- `ipc_server.py` `_handle_enqueue_scan`
- MCP tool `ck3_playset`

### Option B: Always Pass Explicit Path

Require all playset operations to pass explicit path:

```python
# IPC command must include playset_file:
{"command": "enqueue_scan", "params": {"playset_file": "/path/to/playset.json"}}
```

This eliminates ambiguity but requires callers to resolve the path themselves.

## Related Issues

- Bug #1 (--fresh no discovery): Same problem - needs to call `enqueue_playset_roots` after reset
- The `_handle_enqueue_scan` handler DOES correctly call both `enqueue_playset_roots` AND `run_discovery` - this is the correct pattern that `cli.py` should follow

## Testing

1. Start daemon with playset A
2. Use MCP to switch to playset B
3. Verify daemon detects the switch
4. Verify discovery runs for playset B roots
5. Verify build queue contains playset B files
