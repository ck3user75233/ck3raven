# Feature Request: User-Initiated Mode Switching Only

**Priority:** Medium  
**Component:** tools/ck3lens_mcp, policy system  
**Date:** 2026-02-06

---

## Problem Statement

An AI agent incorrectly switched from `ck3lens` mode to `ck3raven-dev` mode without user authorization. The agent misinterpreted context from a conversation summary and began implementing code changes instead of documenting bugs as requested.

This caused:
1. Unauthorized code changes to `qbuilder/cli.py`
2. Confusion about what was requested vs. what was done
3. Need to manually revert changes

## Current Behavior

Any agent can call `ck3_get_mode_instructions(mode="ck3raven-dev")` at any time, which:
- Switches the active mode
- Grants elevated write permissions
- Changes the agent's allowed operations

There is no verification that the user requested the mode switch.

## Proposed Solutions

### Option A: User Token (Recommended - Simplest)

`ck3_get_mode_instructions` requires a `user_token` param for restricted modes:

```python
# ck3lens mode - no token needed (default, safe)
ck3_get_mode_instructions(mode="ck3lens")

# ck3raven-dev mode - requires user-provided token
ck3_get_mode_instructions(mode="ck3raven-dev", user_token="ABC123")
```

**User flow:**
1. User says: "Switch to dev mode, token: ABC123"
2. Agent calls with token
3. If token matches session token, mode switches
4. If no token or wrong token, returns error

**Implementation:**
- Generate session token on MCP server start
- Display to user in VS Code status bar or command palette
- Token rotates each session (prevents stale tokens)

### Option B: Confirmation Gate

Mode switch returns pending state requiring confirmation:

```python
# Agent requests switch
result = ck3_get_mode_instructions(mode="ck3raven-dev")
# result: {"pending": true, "confirmation_code": "CONFIRM-xyz789"}

# User must then run a command or the agent must call:
ck3_confirm_mode(code="CONFIRM-xyz789")  # Only works if user approved
```

**Pros:** Clear audit trail
**Cons:** Extra round-trip, more complex UX

### Option C: Explicit Switch Command

Remove mode parameter from `ck3_get_mode_instructions`. Add separate tool:

```python
# Read-only, returns current mode instructions
ck3_get_mode_instructions()  # No mode param

# Separate command for switching (could be user-facing only)
ck3_switch_mode(mode="ck3raven-dev", reason="Need to fix infrastructure bug")
```

Combined with VS Code command palette for user-initiated switches.

### Option D: Session Lock

First mode initialization locks the session:

```python
# First call locks mode
ck3_get_mode_instructions(mode="ck3lens")  # Session locked to ck3lens

# Subsequent switch requires unlock
ck3_get_mode_instructions(mode="ck3raven-dev")  
# Error: "Session locked to ck3lens. Use ck3_unlock_mode to switch."

# User must approve unlock
ck3_unlock_mode(reason="User requested dev mode")  # Triggers approval UI
```

---

## Recommendation

**Option A (User Token)** is simplest:
- Minimal code change
- User says "switch to dev mode, token: XYZ" 
- Agent cannot fabricate token
- No additional UI needed beyond displaying token

**Token display options:**
1. VS Code status bar item showing current token
2. Command palette: "CK3 Lens: Show Mode Switch Token"
3. In the MCP server boot message

---

## Security Considerations

| Risk | Mitigation |
|------|------------|
| Agent guesses token | Use cryptographic randomness (UUID4 or similar) |
| Token leaked in logs | Never log full token, only last 4 chars |
| Token persists across sessions | Rotate on each MCP server restart |
| User forgets token | Provide easy way to retrieve (command palette) |

---

## Affected Code

- `tools/ck3lens_mcp/server.py` - Mode initialization logic
- `tools/ck3lens_mcp/ck3lens/policy/` - Policy enforcement
- VS Code extension (if adding token display)
