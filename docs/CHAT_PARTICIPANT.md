# @ck3raven Chat Participant

> **Status:** V1 IMPLEMENTED  
> **Last Updated:** January 31, 2026  
> **Location:** `tools/ck3lens-explorer/src/chat/`

---

## Overview

The `@ck3raven` chat participant provides a specialized CK3 modding assistant within VS Code's chat panel. It operates alongside VS Code Copilot, using the same MCP tools but with a focused system prompt.

### Interface Decision

| Interface | Purpose | Use Case |
|-----------|---------|----------|
| **VS Code Copilot + MCP** | Primary interface | Complex multi-step work, architecture changes, debugging |
| **@ck3raven participant** | Secondary interface | Bounded/specialized tasks, quick queries |

The participant is designed for focused, bounded tasks. Complex work should use Copilot directly with MCP tools.

---

## Architecture

### File Structure

```
tools/ck3lens-explorer/src/chat/
├── participant.ts      # Main handler with tool orchestration loop
├── journal.ts          # JSONL writer, session management
├── journalTypes.ts     # TypeScript interfaces for journal events
├── search.ts           # Text search over journal files
├── actions.ts          # Tag/action command handlers
├── diagnose.ts         # Health checks
└── index.ts            # Module exports
```

### Key Components

#### Ck3RavenParticipant ([participant.ts](../tools/ck3lens-explorer/src/chat/participant.ts))

The main chat handler implementing the tool result feedback loop:

```
1. Send messages to LLM with tools list
       ↓
2. Process response stream
   ├── TextPart → stream to user
   └── ToolCallPart → execute via vscode.lm.invokeTool
       ↓
3. If tool calls occurred:
   ├── Append Assistant message with ToolCallParts
   ├── Append User message with ToolResultParts
   └── LOOP BACK to step 1
       ↓
4. When no more tool calls: finalize and log to journal
```

**Critical Implementation Detail:**
```typescript
// Tool results must use .content, not wrap the whole LanguageModelToolResult
iterationToolResults.push({
    callId: toolCall.callId,
    content: result.content  // ✓ CORRECT
});

// Error case must create proper LanguageModelTextPart
content: [new vscode.LanguageModelTextPart(`Error: ${String(error)}`)]
```

#### System Prompt

Minimal 3-line prompt only:

```typescript
private getSystemPrompt(): string {
    return `You are ck3raven.
Use the provided tools when needed.
Tool names are dynamic; use EXACT tool name strings provided in tool list for this request.`;
}
```

No mode documents embedded. No dynamic expansion.

#### Tool Filtering

Conservative filter - only expose ck3_* tools:

```typescript
private getMcpTools(): vscode.LanguageModelChatTool[] {
    return vscode.lm.tools.filter(tool => 
        tool.name.includes('ck3_') || tool.name.includes('ck3lens')
    );
}
```

---

## Journal System

### Purpose

JSONL append-only journaling for all @ck3raven interactions. Enables:
- Session history review
- Tool call auditing
- Tagging important exchanges
- Creating follow-up actions

### Storage Location

```
<workspace-root>/
└── .ck3raven/
    └── chats/
        └── YYYY-MM-DD/
            └── session_ck3raven-YYYYMMDD-<uuid>.jsonl
```

### Event Types

| Event Type | Description |
|------------|-------------|
| `session_start` | Opens a new session |
| `turn` | User prompt + assistant response |
| `tool_call` | Each MCP tool invocation with timing |
| `tag` | Tags applied to a turn |
| `action` | Follow-up action created |
| `health` | Diagnostic snapshot |

### Size Handling (Q6 Decision)

**Never fail due to size. Always write valid JSON.**

Fields exceeding 5MB are truncated with metadata:

```typescript
interface TruncationInfo {
    truncated: true;
    byte_len: number;
    sha256: string;
    preview: string;  // First 1000 chars
}
```

### Journal Writer ([journal.ts](../tools/ck3lens-explorer/src/chat/journal.ts))

Key methods:

```typescript
class JournalWriter {
    ensureSession(): Promise<string>     // Create/get session
    createTurnId(): string               // Generate turn ID (t0001, t0002, ...)
    logTurn(turnId, userText, assistantText, toolCallCount): Promise<void>
    logToolCall(turnId, toolCall): Promise<void>
    logTag(turnId, tags, note?): Promise<void>
    logAction(turnId, title, details?, tags?): Promise<string>
    logHealth(checks): Promise<void>
}
```

Write-through design - no buffering, events written immediately.

---

## Commands

### Registered Commands

| Command | Purpose |
|---------|---------|
| `ck3raven.chatJournal.tagLastTurn` | Tag the most recent turn |
| `ck3raven.chatJournal.createActionFromLastTurn` | Create action from turn |
| `ck3raven.chatJournal.search` | Search across journal files |
| `ck3raven.chatJournal.openFolder` | Reveal journal folder in OS |
| `ck3raven.diagnose` | Run health diagnostics |

### Health Diagnostics

The `ck3raven.diagnose` command checks:
- Participant registration
- Journal writability
- MCP tools registered
- Known extension conflicts (configurable via setting)

---

## Configuration

### Settings

```json
"ck3raven.chatJournal.knownChatRecorderExtensions": {
    "type": "array",
    "default": [],
    "description": "Extension IDs that may conflict with ck3raven journaling"
}
```

### package.json Contributions

```json
"chatParticipants": [
    {
        "id": "ck3raven",
        "name": "ck3raven",
        "fullName": "CK3 Raven",
        "description": "CK3 modding assistant with conflict detection",
        "isSticky": true
    }
]
```

---

## Known Limitations

### Response Truncation
VS Code may truncate long participant responses. This is a platform limitation. For complex work requiring full responses, use Copilot + MCP tools directly.

### maxTokens Setting
The participant requests `maxTokens: 16384` but the actual limit depends on the model.

### No Proposed API Features
The participant uses stable VS Code APIs only. No `@vscode/proposed` dependencies.

---

## Development

### Build

```bash
cd tools/ck3lens-explorer
npm run compile
```

### Watch Mode

```bash
npm run watch
```

### Debug

1. Open ck3raven workspace in VS Code
2. Press F5 to launch Extension Development Host
3. In dev host, open Chat panel and type `@ck3raven hello`

---

## Related Documents

- [CHAT_PARTICIPANT_V1_IMPLEMENTATION_PLAN.md](CHAT_PARTICIPANT_V1_IMPLEMENTATION_PLAN.md) - Original implementation plan with all decisions
- [ARCHITECTURE_TODO_JAN31.md](ARCHITECTURE_TODO_JAN31.md) - Current TODO list
