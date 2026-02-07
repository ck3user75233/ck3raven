# Bug: Paths Doctor Sidebar Status Not Working

**Filed:** 2026-02-07  
**Severity:** Medium  
**Component:** `tools/ck3lens-explorer/src/views/agentView.ts`

---

## Summary

The Paths Doctor status item in the sidebar (which replaced the redundant Python Bridge status) has two failures:

1. **Status not updating** - Should show green checkmark if all paths validate, warning/error icon if issues exist
2. **Click to configure does nothing** - The `ck3lens.openPathsConfig` command doesn't open the config file

---

## Expected Behavior

1. On extension activation, `runPathsDoctor()` should execute and update the tree item with actual status
2. Clicking the "Configure Paths" button should open the user's paths config file (returned by paths_doctor CLI as `config_path`)

---

## Current Behavior

1. Status shows as "unchecked" and never updates
2. Configure command registers but has no visible effect

---

## Root Cause Analysis

### Issue 1: runPathsDoctor() never called on startup

The `runPathsDoctor()` method exists but is never invoked during extension activation. Need to call it in `extension.ts` after registering the agent view.

### Issue 2: openPathsConfig command implementation

The command was registered but the implementation may be incomplete or the config path isn't being captured/stored from the CLI output.

---

## Files Involved

| File | Issue |
|------|-------|
| `views/agentView.ts` | `runPathsDoctor()` exists but not auto-called; config path not stored |
| `extension.ts` | Missing call to trigger paths doctor on activation |

---

## Proposed Fix

1. **In `extension.ts`**: After `registerAgentTreeView()`, call the provider's `runPathsDoctor()` method
2. **In `agentView.ts`**: 
   - Store `config_path` from CLI response in state
   - Implement `openPathsConfig` to use stored path or call CLI to get it
   - Add proper error handling for subprocess failures

---

## Verification Steps

1. Reload VS Code window
2. Check sidebar - Paths Doctor should show green/yellow/red based on actual validation
3. Click configure - should open the paths config file in editor
