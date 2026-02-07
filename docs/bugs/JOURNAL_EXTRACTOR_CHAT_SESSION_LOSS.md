# Bug: Journal Extractor Causes Chat Session Loss on Windows

**Date:** 2026-02-07  
**Status:** FIXED  
**Severity:** High  
**Affects:** Production VS Code window (not ext dev host)

---

## Fix Implementation (2026-02-07)

### Summary

Implemented a multi-phase fix combining Options 1 and 2:
1. **Phase 0**: Skip extraction entirely during `deactivate()` - write pending marker instead
2. **Phase 1**: Re-run extraction at next startup using copy-then-read pattern
3. **Phase 2**: Add defensive guards throughout all chatSessions-touching code

### Files Modified

| File | Change |
|------|--------|
| `windowManager.ts` | Added `isShuttingDown` flag, `writePendingMarker()`, skip extraction when `reason='deactivate'` |
| `startupExtractor.ts` | **NEW** - Copy-then-read extraction at startup |
| `extension.ts` | Call `setShuttingDown(true)` at START of `deactivate()`, schedule startup extraction |
| `discovery.ts` | Added shutdown guards that return early |
| `baseline.ts` | Added shutdown guards that return early |
| `delta.ts` | Added shutdown guards that return early |
| `extractor.ts` | Added shutdown guard at function entry |
| `backends/jsonBackend.ts` | Added shutdown guards to all file-reading functions |
| `journal/index.ts` | Export new functions |

### Key Patterns

**Global shutdown flag (windowManager.ts):**
```typescript
let isShuttingDown = false;
export function getIsShuttingDown(): boolean { return isShuttingDown; }
export function setShuttingDown(value: boolean): void { isShuttingDown = value; }
```

**Startup extraction (startupExtractor.ts):**
```typescript
// 1. Check for pending marker
// 2. Copy chatSessions/*.json → ~/.ck3raven/journals/{workspace}/.snapshot/
// 3. Parse from snapshot only (never touch original)
// 4. Clean up marker and snapshot
```

**Defensive guard pattern:**
```typescript
if (getIsShuttingDown()) {
    return []; // or empty result
}
```

---

## Original Symptoms

- Chat session history disappears after closing VS Code window
- Error in logs: `ChatSessionStore: Error writing chat session Unreachable`
- Only affects the main VS Code window, not the extension development host
- Started occurring after Chat Journal Extractor was implemented

---

## Root Cause Analysis

### The Smoking Gun

**discovery.ts (lines 67-70):**
```typescript
const extensionStoragePath = context.storageUri.fsPath;
const workspaceStorageRoot = path.dirname(extensionStoragePath);
const chatSessionsPath = path.join(workspaceStorageRoot, 'chatSessions');
```

The extension reads directly from `workspaceStorage/{workspace_id}/chatSessions/` - **VS Code's internal storage**.

### Timeline of the Crash

1. **User closes VS Code window**
2. **VS Code wants to write** current chat session to `chatSessions/*.json`
3. **Our `deactivate()` runs** (extension.ts lines 1248-1251):
   ```typescript
   if (journalWindowManager) {
       await journalWindowManager.dispose();  // ← PROBLEM
   }
   ```
4. **`dispose()` calls `closeWindow('deactivate')`** 
5. **`closeWindow()` calls `extractWindow()`** which calls:
   - `detectDelta()` → `fs.readdirSync()` + `fs.statSync()` on chatSessions files
   - `parseSessionFile()` → `fs.readFileSync()` on changed files
6. **On Windows**: Our file reads **block VS Code's writes** (sharing violation)
7. **VS Code's write fails** → `ChatSessionStore: Error writing chat session Unreachable`
8. **Chat history is lost**

### Why Ext Dev Host Works

The ext dev host is running YOUR extension in a child process. When you close that window:
- The ext dev host terminates without running your production `deactivate()`
- Or the timing is different because it's not your main VS Code instance

### File Operations That Cause Locks

| File | Operation | Called During |
|------|-----------|---------------|
| baseline.ts line 28 | `fs.readdirSync(chatSessionsPath)` | Window start |
| baseline.ts line 34 | `fs.statSync(filePath)` | Window start |
| delta.ts line 37 | `fs.readdirSync(chatSessionsPath)` | **SHUTDOWN** |
| delta.ts line 46 | `fs.statSync(filePath)` | **SHUTDOWN** |
| jsonBackend.ts line 67 | `fs.readFileSync(filePath)` | **SHUTDOWN** |

---

## Files Involved

- `tools/ck3lens-explorer/src/journal/discovery.ts` - Finds chatSessions path
- `tools/ck3lens-explorer/src/journal/baseline.ts` - Creates baseline snapshot
- `tools/ck3lens-explorer/src/journal/delta.ts` - Detects changes since baseline
- `tools/ck3lens-explorer/src/journal/backends/jsonBackend.ts` - Reads session JSON files
- `tools/ck3lens-explorer/src/journal/extractor.ts` - Orchestrates extraction
- `tools/ck3lens-explorer/src/journal/windowManager.ts` - Manages window lifecycle, calls extraction on dispose
- `tools/ck3lens-explorer/src/journal/startupExtractor.ts` - **NEW** Safe startup extraction
- `tools/ck3lens-explorer/src/extension.ts` - Calls windowManager.dispose() in deactivate()
