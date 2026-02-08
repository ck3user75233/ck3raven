# Chat Journaling v2.0 - Canonical Architecture

> **Status:** Design (v1.0 DISABLED as of 2026-02-08)  
> **Author:** CK3 Lens Team  
> **Last Updated:** 2026-02-08

---

## Executive Summary

Chat Journaling v1.0 has been **emergency disabled** due to suspected file locking conflicts with VS Code's ChatSessionStore. The extension was reading VS Code's live `chatSessions` folder while VS Code was running, causing "ChatSessionStore: Error writing chat session Unreachable" errors and loss of chat history on window reload.

**v2.0 Architecture Principle:** Never touch VS Code's files while VS Code is running.

---

## Problem Statement

### v1.0 Failure Mode

```
Timeline (2026-02-08):
21:09:50 - VS Code window reload initiated
21:09:53 - New extension host started
21:09:58 - Our startupExtractor copied 23 files from chatSessions (fs.readFileSync)
21:10:52 - FIRST ERROR: "ChatSessionStore: Error writing chat session Unreachable"
21:10:52+ - Errors continue every minute
           - Chat session never persisted
           - On next reload, reverted to old session
```

### Root Cause Hypothesis

On Windows, `fs.readFileSync()` acquires a shared read lock. Even after the read completes, Node.js may not immediately release the file handle. If VS Code's ChatSessionStore needs exclusive write access during this window, it fails with "Unreachable".

### Hard Requirements for v2.0

1. **NEVER read/copy chatSessions while VS Code is running**
2. **Extraction must happen via external process** (one-shot, dies completely)
3. **Process death = OS forcibly releases all handles** (no lingering locks)
4. **Fail-fast on any file access error** (don't hold handles waiting)

---

## Architecture Overview

### Variant A: Watcher-Based (Best UX)

```
┌─────────────────────────────────────────────────────────────────┐
│                      WHILE VS CODE RUNNING                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Extension (ck3lens-explorer)                                    │
│  ├── Collects workspace storage paths from extensionContext      │
│  ├── Writes manifest to ~/.ck3raven/journal_manifest.json        │
│  │   • workspace_name                                            │
│  │   • workspace_storage_root                                    │
│  │   • last_seen_timestamp                                       │
│  │   • user_data_dir (optional)                                  │
│  └── DOES NOT touch chatSessions files AT ALL                    │
│                                                                  │
│  Watcher Process (detached, Python or exe)                       │
│  ├── Runs independently of VS Code                               │
│  ├── Every N minutes: check if VS Code process is running        │
│  └── If NOT running → spawn one-shot extractor → sleep/exit      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    WHEN VS CODE IS CLOSED                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  One-Shot Extractor (Python subprocess)                          │
│  ├── Reads manifest → gets workspace storage paths               │
│  ├── For each workspace:                                         │
│  │   ├── open chatSessions/*.jsonl                               │
│  │   ├── read content                                            │
│  │   ├── close immediately                                       │
│  │   ├── write to ~/.ck3raven/journals/{workspace}/archives/     │
│  │   └── continue to next file                                   │
│  ├── If ANY file fails → log error and skip (don't block)        │
│  └── EXIT (process death = all handles released)                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Variant B: CLI-Based (Simpler, Recommended First)

```
┌─────────────────────────────────────────────────────────────────┐
│                      WHILE VS CODE RUNNING                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Extension (ck3lens-explorer)                                    │
│  └── Same as Variant A: collect paths, write manifest            │
│      NEVER touch chatSessions                                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    AFTER USER CLOSES VS CODE                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User runs:                                                      │
│  $ ck3lens-export-chats                                          │
│                                                                  │
│  CLI does same as Variant A's extractor                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Why Variant B first:**
- Zero background behavior (no surprises)
- Easy to test causality ("did chat flushing stop?")
- Easy to support ("close VS Code → run exporter")
- Once stable, add Variant A's watcher as convenience layer

---

## Component Specifications

### 1. Manifest File

**Location:** `~/.ck3raven/journal_manifest.json`

```json
{
  "version": "2.0",
  "last_updated": "2026-02-08T21:30:00Z",
  "workspaces": [
    {
      "workspace_key": "c44ef3a737f410f8638b643bd9bd9178",
      "workspace_name": "ck3raven multi-root",
      "storage_root": "C:\\Users\\nateb\\AppData\\Roaming\\Code\\User\\workspaceStorage\\c44ef3a737f410f8638b643bd9bd9178",
      "chat_sessions_path": "C:\\Users\\nateb\\AppData\\Roaming\\Code\\User\\workspaceStorage\\c44ef3a737f410f8638b643bd9bd9178\\chatSessions",
      "last_seen": "2026-02-08T21:30:00Z"
    }
  ]
}
```

**How it's collected:**
```typescript
// In extension activate()
const storageUri = context.storageUri;  // VS Code API - safe
const workspaceStorageRoot = path.dirname(storageUri.fsPath);
const chatSessionsPath = path.join(workspaceStorageRoot, 'chatSessions');
// Write to manifest - NO reads of chatSessions!
```

### 2. Extension Responsibilities (While Running)

```typescript
// ALLOWED:
// - Get paths from extensionContext API
// - Write manifest file in our own storage
// - Register commands, status bar, tree view
// - Show existing archives in tree view (from our storage)

// FORBIDDEN:
// - fs.readFileSync on chatSessions
// - fs.existsSync on chatSessions (even this acquires a handle briefly!)
// - fs.readdirSync on chatSessions
// - ANY file operation on workspaceStorage/*/chatSessions/*
```

### 3. One-Shot Extractor (Python)

**Location:** `tools/journal_extractor/extract.py`

```python
#!/usr/bin/env python3
"""
One-shot chat session extractor.
MUST be run when VS Code is NOT running.
Process exits completely after extraction - no lingering handles.
"""

import json
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime

def is_vscode_running() -> bool:
    """Check if VS Code process is running."""
    import psutil
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] in ('Code.exe', 'Code', 'code'):
            return True
    return False

def extract_workspace(workspace: dict, output_root: Path) -> dict:
    """Extract chat sessions from one workspace."""
    result = {
        'workspace_key': workspace['workspace_key'],
        'files_extracted': 0,
        'errors': []
    }
    
    chat_path = Path(workspace['chat_sessions_path'])
    if not chat_path.exists():
        result['errors'].append(f"Path does not exist: {chat_path}")
        return result
    
    output_dir = output_root / workspace['workspace_key'] / 'raw'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for file in chat_path.glob('*.jsonl'):
        try:
            # CRITICAL: Open → Read → Close → Write
            # Minimize time holding source file handle
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Write to our storage
            dest = output_dir / file.name
            with open(dest, 'w', encoding='utf-8') as f:
                f.write(content)
            
            result['files_extracted'] += 1
            
        except Exception as e:
            # Log and continue - don't block on one file
            result['errors'].append(f"{file.name}: {str(e)}")
    
    return result

def main():
    # GUARD: Refuse to run if VS Code is running
    if is_vscode_running():
        print(json.dumps({
            'success': False,
            'error': 'VS Code is running. Close it first.',
            'hint': 'This extractor must run when VS Code is completely closed.'
        }))
        sys.exit(1)
    
    # Load manifest
    manifest_path = Path.home() / '.ck3raven' / 'journal_manifest.json'
    if not manifest_path.exists():
        print(json.dumps({
            'success': False,
            'error': f'Manifest not found: {manifest_path}',
            'hint': 'Run VS Code with CK3 Lens extension first to generate manifest.'
        }))
        sys.exit(1)
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    # Extract from each workspace
    output_root = Path.home() / '.ck3raven' / 'journals'
    results = []
    
    for workspace in manifest.get('workspaces', []):
        result = extract_workspace(workspace, output_root)
        results.append(result)
    
    # Summary
    total_files = sum(r['files_extracted'] for r in results)
    total_errors = sum(len(r['errors']) for r in results)
    
    print(json.dumps({
        'success': True,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'workspaces_processed': len(results),
        'files_extracted': total_files,
        'errors': total_errors,
        'details': results
    }, indent=2))

if __name__ == '__main__':
    main()
```

### 4. CLI Wrapper

**Location:** Entry point in `pyproject.toml`

```toml
[project.scripts]
ck3lens-export-chats = "ck3raven.tools.journal_extractor:main"
```

**Usage:**
```bash
# After closing VS Code:
$ ck3lens-export-chats

# Output:
{
  "success": true,
  "timestamp": "2026-02-08T22:00:00Z",
  "workspaces_processed": 2,
  "files_extracted": 15,
  "errors": 0,
  "details": [...]
}
```

### 5. Watcher Process (Variant A, Phase 2)

**Location:** `tools/journal_extractor/watcher.py`

```python
"""
Background watcher that extracts chats when VS Code closes.
Runs as detached process, survives VS Code restarts.
"""

import time
import subprocess
import sys
from pathlib import Path

POLL_INTERVAL_SECONDS = 60  # Check every minute

def main():
    extractor = Path(__file__).parent / 'extract.py'
    python = sys.executable
    
    while True:
        if not is_vscode_running():
            # VS Code closed - run extraction
            subprocess.run([python, str(extractor)], check=False)
            # Go back to sleep - VS Code might reopen
        
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == '__main__':
    main()
```

**How it's started:**
```typescript
// Extension activation (if user opts in)
const watcherPath = path.join(extensionPath, 'tools', 'journal_extractor', 'watcher.py');
const proc = spawn(pythonPath, [watcherPath], {
    detached: true,
    stdio: 'ignore',
});
proc.unref();  // Detach from Node process tree
```

---

## Tree View Architecture

The existing tree view implementation remains mostly unchanged, but with different data source.

### Current Structure (Preserved)

```
CK3 LENS EXPLORER
├── Journal
│   ├── [Status: Active / Disabled]
│   └── Archives
│       ├── 2026-02-08
│       │   ├── session_abc123.md
│       │   └── session_def456.md
│       └── 2026-02-07
│           └── session_xyz789.md
├── Agent Mode
│   └── [Current Mode]
└── Tools
    └── [MCP Tools]
```

### Data Flow (v2.0)

```
CLI/Watcher extracts to:
  ~/.ck3raven/journals/{workspace_key}/raw/*.jsonl

Extension reads from:
  ~/.ck3raven/journals/{workspace_key}/archives/*.md
  (converted from raw by extraction process)

Tree view displays:
  Archives grouped by date, then by session
```

---

## Safety Rules (HARD REQUIREMENTS)

### Rule 1: No ChatSessions Access While Running

```typescript
// extension.ts
const JOURNAL_V1_ENABLED = false;  // KILL SWITCH

// If re-enabling in future:
// ONLY write manifest, NEVER read chatSessions
```

### Rule 2: External Process Only

```python
# extract.py
if is_vscode_running():
    sys.exit(1)  # REFUSE to run
```

### Rule 3: One-Shot Semantics

```python
# Extractor process flow:
# 1. Check VS Code not running
# 2. For each file: open → read → close → write
# 3. Exit completely
# 
# NO:
# - Long-running file watches
# - Keeping handles open between files
# - Retry loops that hold handles
```

### Rule 4: Fail Fast

```python
try:
    content = open(file).read()
except Exception as e:
    log_error(e)
    continue  # Skip this file, don't block
```

---

## Migration Path

### Phase 1: Emergency (DONE - 2026-02-08)
- [x] Kill switch added: `JOURNAL_V1_ENABLED = false`
- [x] All chatSessions access disabled
- [x] Commit: `8dfac67`

### Phase 2: Manifest Collection
- [ ] Extension writes manifest on activate (paths only, no file reads)
- [ ] Validate manifest contains correct paths

### Phase 3: CLI Extractor (Variant B)
- [ ] Implement `extract.py`
- [ ] Add `ck3lens-export-chats` CLI entry point
- [ ] Test extraction with VS Code closed
- [ ] Convert raw JSONL to markdown archives

### Phase 4: Background Watcher (Variant A)
- [ ] Implement `watcher.py`
- [ ] Add opt-in setting in extension
- [ ] Detached process spawning

### Phase 5: Tree View Integration
- [ ] Tree view reads from our archive directory
- [ ] Shows extraction status
- [ ] "Run Extraction" command (refuses if VS Code open)

---

## Testing Checklist

- [ ] Extension activates without ANY chatSessions file access
- [ ] Manifest is written correctly with workspace paths
- [ ] CLI extractor refuses to run when VS Code is open
- [ ] CLI extractor successfully copies files when VS Code is closed
- [ ] Process exits completely (check with Process Explorer)
- [ ] No "ChatSessionStore: Unreachable" errors after 24h test
- [ ] Chat history persists across window reloads

---

## Appendix: Why Not Just Fix Node.js Locking?

We considered:
1. **Async reads (`fs.promises.readFile`)** - Still acquires handle, just non-blocking
2. **Delay extraction** - Doesn't help, VS Code writes at unpredictable times
3. **Copy with `fs.copyFile`** - Still needs read handle on source
4. **Shadow copies (VSS)** - Requires admin, overkill
5. **Robocopy /B** - Windows-only, external dependency

The fundamental problem is: **any in-process file access can interfere with VS Code while it's running.** The only safe approach is extraction via external process when VS Code is closed.

---

## References

- [VS Code Workspace Storage](https://code.visualstudio.com/api/extension-capabilities/common-capabilities#data-storage)
- [Windows File Locking](https://docs.microsoft.com/en-us/windows/win32/fileio/locking-and-unlocking-byte-ranges-in-files)
- [Node.js fs module handle behavior](https://nodejs.org/api/fs.html)
- Incident: ChatSessionStore errors - 2026-02-08
