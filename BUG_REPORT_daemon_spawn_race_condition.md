# Bug Report: QBuilder Daemon Spawn Race Condition Causes Parser Timeouts

**Date:** 2026-01-26  
**Severity:** CRITICAL  
**Component:** `qbuilder/` daemon architecture + `tools/ck3lens_mcp/` spawn logic  
**Affects:** All file parsing via QBuilder daemon

---

## Summary

Multiple QBuilder daemon processes spawn simultaneously due to a race condition in the MCP layer, causing resource contention that manifests as 30-second parse timeouts. Files that parse in <1 second via direct MCP tool calls timeout when processed by the daemon.

---

## Symptoms

1. **340+ files timing out at exactly 30 seconds** (the configured timeout)
2. **Small files timeout while large files succeed** - a 9-byte file (`# none`) times out while 61KB files parse fine
3. **Multiple daemon processes visible** - observed 2-3 daemon PIDs running concurrently
4. **Multiple parse subprocesses for same file** - observed 2 subprocesses both trying to parse identical file

---

## Root Cause Analysis

### The Race Condition

```
Timeline (actual observed behavior):
────────────────────────────────────────────────────────────────────
T+0.000  MCP Server A: daemon.is_available() → False
T+0.001  MCP Server B: daemon.is_available() → False  
T+0.002  MCP Server A: subprocess.Popen("qbuilder daemon")  → PID 8736
T+0.003  MCP Server B: subprocess.Popen("qbuilder daemon")  → PID 20940
T+0.500  Daemon 8736: WriterLock.acquire() → SUCCESS
T+0.501  Daemon 20940: WriterLock.acquire() → FAIL (but process already running!)
T+1.000  Daemon 8736: IPC server listening on port 19876
T+1.001  Daemon 20940: Crashes or exits (but may have already claimed queue items)
────────────────────────────────────────────────────────────────────
```

### Why Multiple MCP Servers Exist

Observed 4 MCP server processes (2 parent + 2 child pairs):
```
PID 31604 (1:46:26 am) → child PID 8940
PID 28176 (2:24:36 am) → child PID 17472
```

This likely indicates 2 VS Code windows or extension restarts without cleanup.

### Spawn Points (3 locations, all vulnerable)

| Location | Trigger | File |
|----------|---------|------|
| `ck3_qbuilder(command="build")` | Explicit user request | `server.py:5396` |
| `_auto_start_daemon()` | After file writes | `unified_tools.py:1525` |
| Mode initialization | During playset switch | `server.py:2109` |

### The Writer Lock Gap

The writer lock (`qbuilder/writer_lock.py`) correctly prevents **two daemons from writing to the database simultaneously**. However, it does NOT prevent:

1. Multiple daemon processes from **spawning**
2. Multiple daemon processes from **claiming queue items before lock check**
3. Multiple parse **subprocesses** from launching for the same file

---

## Evidence

### Process List (captured during investigation)

```
ProcessId   CommandLine
---------   -----------
8736        python.exe -m qbuilder.cli daemon    ← Daemon 1
20940       python.exe -m qbuilder.cli daemon    ← Daemon 2 (SHOULD NOT EXIST)
22916       python.exe -c "...parse_file..."     ← Parse subprocess 1
7560        python.exe -c "...parse_file..."     ← Parse subprocess 2 (SAME FILE!)
```

Both daemons started at **exactly the same second** (3:12:17 am).

### Same File Parsed Twice

Both parse subprocesses were attempting to parse:
```
C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310\3422759424\common\modifiers\BKT_war_and_combat_modifiers.txt
```

### Direct Parse vs Daemon Parse

| Method | File | Result |
|--------|------|--------|
| `ck3_parse_content()` MCP tool | 437-line MAA file | **0.02 seconds** |
| QBuilder daemon subprocess | Same file | **30s TIMEOUT** |

The parser code is identical - the timeout is caused by resource contention.

---

## Affected Code

### `tools/ck3lens_mcp/ck3lens/unified_tools.py`

```python
# Line 1525 - NO LOCK CHECK BEFORE SPAWN
def _auto_start_daemon():
    """..."""
    # MISSING: Check if writer lock is already held
    subprocess.Popen(  # ← RACE CONDITION HERE
        [python_exe, "-m", "qbuilder.cli", "daemon"],
        ...
    )
```

### `tools/ck3lens_mcp/server.py`

```python
# Line 2109 - Same pattern
subprocess.Popen(
    [str(venv_python), "-m", "qbuilder", "daemon"],
    ...
)

# Line 5396 - Same pattern (ck3_qbuilder command)
proc = subprocess.Popen(
    [python_exe, "-m", "qbuilder.cli", "daemon"],
    ...
)
```

---

## Proposed Fix

### Option 1: Check Writer Lock Before Spawn (Recommended)

Modify all spawn points to check the writer lock BEFORE spawning:

```python
def _auto_start_daemon():
    """Attempt to auto-start the QBuilder daemon as a background process.
    
    RACE CONDITION PROTECTION:
    - Checks writer lock BEFORE spawning to prevent multiple spawn attempts
    - If lock is held but IPC not available, waits for daemon to finish starting
    """
    import subprocess
    import sys
    import time
    from pathlib import Path
    from ck3lens.daemon_client import daemon
    
    # Add qbuilder to path for writer_lock import
    project_root = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(project_root))
    from qbuilder.writer_lock import check_writer_lock
    
    db_path = Path.home() / ".ck3raven" / "ck3raven.db"
    python_exe = sys.executable
    
    # CRITICAL: Check writer lock BEFORE spawning
    lock_status = check_writer_lock(db_path)
    
    if lock_status.get("lock_exists") and lock_status.get("holder_alive"):
        # Another daemon holds the lock - wait for IPC to become available
        for _ in range(10):  # Wait up to 5 seconds
            time.sleep(0.5)
            if daemon.is_available(force_check=True):
                return True
        # Lock holder exists but IPC not responding - something is wrong
        return False
    
    # No lock holder - safe to spawn
    try:
        import platform
        
        if platform.system() == "Windows":
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [python_exe, "-m", "qbuilder.cli", "daemon"],
                cwd=str(project_root),
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [python_exe, "-m", "qbuilder.cli", "daemon"],
                cwd=str(project_root),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        
        # Wait for daemon to start
        time.sleep(2)
        
        return daemon.is_available(force_check=True)
        
    except Exception:
        return False
```

### Option 2: Add Spawn Lock File

Create a separate spawn lock that's acquired BEFORE subprocess.Popen:

```python
import filelock  # pip install filelock

SPAWN_LOCK_PATH = Path.home() / ".ck3raven" / "daemon_spawn.lock"

def _auto_start_daemon():
    """Auto-start daemon with spawn-level locking to prevent race conditions."""
    from ck3lens.daemon_client import daemon
    
    try:
        # Acquire spawn lock with short timeout
        # Only ONE process can hold this lock at a time
        with filelock.FileLock(SPAWN_LOCK_PATH, timeout=5):
            # Double-check: daemon might have started while we waited for lock
            if daemon.is_available(force_check=True):
                return True
            
            # We have the spawn lock and daemon isn't running - safe to spawn
            subprocess.Popen(
                [python_exe, "-m", "qbuilder.cli", "daemon"],
                ...
            )
            
            time.sleep(2)
            return daemon.is_available(force_check=True)
            
    except filelock.Timeout:
        # Another process is spawning - wait for daemon to appear
        for _ in range(10):
            time.sleep(0.5)
            if daemon.is_available(force_check=True):
                return True
        return False
```

### Option 3: Remove Auto-Start (Simplest)

Remove `_auto_start_daemon()` entirely. Require explicit daemon start:

```python
def _refresh_file_in_db_internal(absolute_path, mod_name=None, rel_path=None, deleted=False):
    """..."""
    from ck3lens.daemon_client import daemon, DaemonNotAvailableError
    
    if not daemon.is_available(force_check=True):
        # DON'T auto-start - just return gracefully
        return {
            "success": False,
            "queued": False,
            "error": "Daemon not running",
            "hint": "Start daemon with: ck3_qbuilder(command='build')",
        }
    
    # ... rest of function
```

This is the simplest fix but requires user to manually start daemon once per session.

---

## Verification Steps

### Before Fix (Reproduce the Bug)

1. Kill all Python processes:
   ```powershell
   Get-Process python* | Stop-Process -Force
   ```

2. Open 2 VS Code windows with the same workspace

3. In both windows simultaneously, trigger playset switch or file save

4. Check for multiple daemons:
   ```powershell
   Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -like "*qbuilder*daemon*"} | Select-Object ProcessId
   ```

5. Observe multiple PIDs (bug confirmed)

### After Fix (Verify Fix Works)

1. Kill all Python processes

2. Start single daemon: `ck3_qbuilder(command="build")`

3. Open second VS Code window, trigger daemon spawn attempt

4. Verify only ONE daemon exists:
   ```powershell
   Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -like "*qbuilder*daemon*"} | Select-Object ProcessId
   ```

5. Run queue processing - verify no timeouts on small files

---

## Related Issues

### Parser Timeout Reports Are Symptoms, Not Root Cause

The 340 "timing out" files documented in `SUGGESTION_routing_table_exclusions.md` are NOT parser bugs:

| File | Size | Via MCP Tool | Via Daemon |
|------|------|--------------|------------|
| `07_balgarsko_templates.txt` | 9 bytes | <1ms | 30s TIMEOUT |
| `33_mamluk_story_cycle.txt` | 14 bytes | <1ms | 30s TIMEOUT |
| `kBKT_mpo_maa_types.txt` | 437 lines | 20ms | 30s TIMEOUT |

All these files parse instantly when daemon contention is eliminated.

### Not Parser Encoding Issues

Earlier hypothesis about BOM (`\ufeff`) causing issues was incorrect:
- The parser correctly handles BOM via `encoding='utf-8-sig'`
- Direct `ck3_parse_content()` works fine with BOM content
- Timeout is due to subprocess resource contention, not encoding

---

## Files to Modify

| File | Change |
|------|--------|
| `tools/ck3lens_mcp/ck3lens/unified_tools.py` | Add lock check to `_auto_start_daemon()` (line 1525) |
| `tools/ck3lens_mcp/server.py` | Add lock check to spawn logic (lines 2109, 5396) |
| `docs/SINGLE_WRITER_ARCHITECTURE.md` | Document spawn-time lock requirement |

---

## Architecture Diagram

```
CURRENT (Buggy):
                                                  
  MCP Server A ──┐                               
                 ├─→ Both check is_available() → False
  MCP Server B ──┘                               
                 ├─→ Both spawn daemon processes
                 ↓                               
         ┌───────────────┐    ┌───────────────┐  
         │  Daemon PID X │    │  Daemon PID Y │  
         └───────┬───────┘    └───────┬───────┘  
                 ↓                    ↓          
         Acquire Lock ✓         Acquire Lock ✗   
                 ↓                    ↓          
         Process Queue          CRASH (but too late!)
                 ↓                               
         Spawn Parse            Already spawned parse
         Subprocess             subprocess too!   
                                                  

FIXED:
                                                  
  MCP Server A ──┐                               
                 ├─→ Both check WRITER LOCK first
  MCP Server B ──┘                               
                 ↓                               
         ┌─────────────────────────────────────┐ 
         │  A: Lock not held → spawn daemon    │ 
         │  B: Lock held → wait for IPC        │ 
         └─────────────────────────────────────┘ 
                 ↓                               
         Only ONE daemon spawns                  
                 ↓                               
         Process Queue (no contention)           
                 ↓                               
         Parse succeeds in milliseconds          
```

---

## Priority

**CRITICAL** - This bug blocks all QBuilder processing and creates cascading failures:
- 340+ files stuck in timeout state
- Queue never completes
- Symbol/reference extraction blocked
- MCP search tools return incomplete results

---

## Testing Checklist

- [ ] Single daemon spawns when multiple MCP servers trigger simultaneously
- [ ] Second spawn attempt waits and connects to existing daemon
- [ ] 9-byte comment-only files parse in <100ms
- [ ] Queue drains completely without timeouts
- [ ] No "Parse timeout after 30s" errors in qbuilder log
