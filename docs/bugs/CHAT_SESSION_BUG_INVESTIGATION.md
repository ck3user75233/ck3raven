# Chat Session Storage Bug Investigation

**Date:** February 7, 2026  
**Issue:** VS Code Copilot chat sessions not saving in ck3raven workspace (started ~Feb 5-6)

---

## Problem Summary

Chat sessions in the ck3raven workspace window are NOT being saved. Sessions work fine in:
- Extension Development Host window
- Other workspaces (parent folder window)

---

## Root Cause Identified

**Error in VS Code logs:**
```
[error] [UriError]: Scheme contains illegal characters.
```

This error occurs at window startup BEFORE the ChatSessionStore errors begin. It corrupts VS Code's internal state, making chat storage "Unreachable" for the entire session.

**Subsequent symptom (repeating every ~60 seconds):**
```
[error] ChatSessionStore: Error writing chat session Unreachable
```

---

## Current Status

**Ruled Out:**
- ❌ Journal extractor locking files (fixed shutdown behavior, no impact)
- ❌ Corrupted data in existing session files (scanned, all valid)
- ❌ File permissions (user has FullControl)
- ❌ Disk space issues (not indicated)
- ❌ Corrupted workspace storage (reset storage folder - still broken)
- ❌ Oracle.oracle-java extension (disabled - still broken)

**Hypothesis #3 ELIMINATED:** Fresh workspace storage did NOT fix the issue. The bug occurs WITHOUT any cached state.

---

## Next Steps (Do These Now)

### Step 1: Check NEW Logs for URIError

After the workspace storage reset, a fresh `renderer.log` was created. Check it:

```
%APPDATA%\Code\logs\[LATEST TIMESTAMP]\window1\renderer.log
```

Search for:
- `UriError`
- `illegal`
- `Scheme`

**If URIError still appears**: Note the EXACT timestamp and what's around it. This will identify which extension is generating the bad URI.

**If NO URIError but still Unreachable**: The problem is different from what we thought.

---

### Step 2: Try Opening as Plain Folder (Not .code-workspace)

This tests if the `.code-workspace` file format is the trigger:

1. Close the ck3raven window
2. File → Open Folder → Navigate to `C:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven`
3. Open as **FOLDER** (not the .code-workspace file)
4. Test if chat sessions save

**If FIXED**: The problem is in the .code-workspace file itself. Next: diff the workspace file for suspicious entries.

**If STILL BROKEN**: Problem is specific to THIS folder, not the workspace file format.

---

### Step 3: Disable Extensions One-by-One

If folder mode still broken, systematically disable:

| Priority | Extension | Why Suspicious |
|----------|-----------|----------------|
| 1 | ms-python.vscode-pylance | Heavy, uses lots of URIs for Python analysis |
| 2 | ms-python.python | Python extension suite root |
| 3 | ms-vscode.js-debug | Debug extension errors seen in logs |
| 4 | ms-python.debugpy | Debugger |

**Test after EACH disable** - reload window and check if "Unreachable" errors stop.

---

### Step 4: Nuclear Option - New Clean Window

If nothing else works:

1. Create a NEW VS Code window (File → New Window)
2. Open the ck3raven folder in that window
3. Manually disable ALL extensions except core ones
4. Test chat sessions
5. Re-enable extensions one by one to find culprit

---

## Key Evidence (Reference)

### Comparison Table

| Metric | ck3raven (BROKEN) | Parent Folder (WORKING) |
|--------|-------------------|------------------------|
| Workspace Type | `.code-workspace` file | Plain folder |
| Storage Hash | `1baa53e28f1eff8e1933787ea3947b07` | `60a79ea760f4bc856061cdee1574a20b` |
| URIError at startup | YES | NO |
| ChatSessionStore Unreachable | 13+ errors/session | 0 |

### Extension Differences (ONLY in broken window)

- ~~Oracle.oracle-java~~ (disabled, still broken)
- ms-python.debugpy
- ms-python.python  
- ms-python.vscode-pylance
- ms-python.vscode-python-envs
- ms-vscode.js-debug

### Data Integrity Check

Scanned ALL storage locations for invalid URI schemes - **NONE FOUND**:
- `state.vscdb` - 121 rows, 0 invalid schemes
- `chatSessions/*.json` - 14 files, 0 invalid schemes
- `GitHub.copilot-chat/*.db` - 2 databases, 0 invalid schemes

**Conclusion:** The invalid URI is generated dynamically at runtime by an extension.

---

## Log Locations Reference

| Log Type | Path |
|----------|------|
| Renderer logs | `%APPDATA%\Code\logs\[timestamp]\window1\renderer.log` |
| Extension host | `%APPDATA%\Code\logs\[timestamp]\window1\exthost\exthost.log` |
| Copilot Chat logs | `%APPDATA%\Code\logs\[timestamp]\window1\exthost\GitHub.copilot-chat\` |
| Workspace storage | `%APPDATA%\Code\User\workspaceStorage\1baa53e28f1eff8e1933787ea3947b07\` |

---

## Updated Hypothesis

Since storage reset didn't help, the URIError is being generated LIVE by:

1. **An extension** that activates specifically for this workspace/folder
2. **Something in the folder structure** that triggers bad URI construction (unlikely)
3. **Workspace configuration** in `.code-workspace` file (needs test via folder-open)

Most likely: **Pylance or Python extension** generating a malformed URI when analyzing this Python project.
