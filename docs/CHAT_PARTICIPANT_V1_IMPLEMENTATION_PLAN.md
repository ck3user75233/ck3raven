# Chat Participant V1 Implementation Plan

> **Status:** APPROVED v2.1 — Implementation may proceed  
> **Created:** January 31, 2026  
> **Updated:** January 31, 2026 (final revisions per patch list)  
> **Based on:** [ck3raven Chat Participant V1 Brief](ck3raven%20Chat%20Participant%20V1%20Brief.md)  
> **Author:** AI Implementation Agent

---

## Decision Lock Summary

All queries have been answered. These decisions are **final for V1**:

| Query | Decision |
|-------|----------|
| Q1: MCP Orchestration | **Option A** - Direct `vscode.lm.invokeTool` with result feedback loop |
| Q2: Session Scope | **Per-workspace** - Session IDs scoped to workspace |
| Q3: Journal Location | **Workspace root** - `/.ck3raven/chats/YYYY-MM-DD/` (append-only JSONL) |
| Q4: Tool Set Filtering | **Conservative filter** - Only tools matching MCP namespace for this instance |
| Q5: System Prompt | **Minimal only** - Do NOT embed mode docs |
| Q6: Size Limits | **Yes, with truncation** - Never fail; use preview + sha256 + byte_len |
| Q7: UUID | **No dependency** - `crypto.randomUUID()` with fallback |

### Scope Lock

- ✅ Follow V1 Brief exactly
- ❌ Do NOT add V2 features (SQLite index, viewer)
- ❌ Do NOT hook Copilot internals or other participants

---

## Table of Contents

1. [Package.json Contributions](#1-packagejson-contributions)
2. [File/Module Layout](#2-filemodule-layout)
3. [Journal Storage Architecture](#3-journal-storage-architecture)
4. [Participant Handler Design](#4-participant-handler-design)
5. [Implementation Phases](#5-implementation-phases)
6. [Non-Negotiable Acceptance Tests](#6-non-negotiable-acceptance-tests)
7. [Estimated Effort](#7-estimated-effort)

---

## 1. Package.json Contributions

### 1.1 Chat Participant Registration

Add to `contributes` section in `tools/ck3lens-explorer/package.json`:

```json
"chatParticipants": [
  {
    "id": "ck3raven",
    "name": "ck3raven",
    "fullName": "CK3 Raven",
    "description": "CK3 modding assistant with conflict detection and mod editing",
    "isSticky": true
  }
]
```

### 1.2 New Commands

Add to existing `commands` array:

```json
{
  "command": "ck3raven.chatJournal.tagLastTurn",
  "title": "CK3 Raven: Tag Last Chat Turn",
  "icon": "$(tag)"
},
{
  "command": "ck3raven.chatJournal.createActionFromLastTurn",
  "title": "CK3 Raven: Create Action from Last Turn",
  "icon": "$(tasklist)"
},
{
  "command": "ck3raven.chatJournal.search",
  "title": "CK3 Raven: Search Chat Journal",
  "icon": "$(search)"
},
{
  "command": "ck3raven.diagnose",
  "title": "CK3 Raven: Run Diagnostics",
  "icon": "$(pulse)"
},
{
  "command": "ck3raven.chatJournal.openFolder",
  "title": "CK3 Raven: Open Chat Journal Folder",
  "icon": "$(folder-opened)"
}
```

### 1.3 New Configuration Setting

Add to `configuration.properties`:

```json
"ck3raven.chatJournal.knownChatRecorderExtensions": {
  "type": "array",
  "items": {
    "type": "string"
  },
  "default": [],
  "description": "Extension IDs that may conflict with ck3raven chat journaling. Extensions in this list trigger a warning in diagnostics."
}
```

### 1.4 Command Summary

| Command ID | Title | Purpose |
|------------|-------|---------|
| `ck3raven.chatJournal.tagLastTurn` | Tag Last Chat Turn | Tag the most recent turn with user-selected tags |
| `ck3raven.chatJournal.createActionFromLastTurn` | Create Action from Last Turn | Create a follow-up action referencing last turn |
| `ck3raven.chatJournal.search` | Search Chat Journal | Text search across journal JSONL files |
| `ck3raven.diagnose` | Run Diagnostics | Print health snapshot (participant, journal, MCP) |
| `ck3raven.chatJournal.openFolder` | Open Chat Journal Folder | Reveal journal folder in OS |

---

## 2. File/Module Layout

### 2.1 New Directory Structure

```
tools/ck3lens-explorer/src/
├── chat/
│   ├── participant.ts      # Registers @ck3raven, handles requests, tool orchestration
│   ├── journal.ts          # JSONL writer, session management, size limits
│   ├── journalTypes.ts     # TypeScript interfaces for journal events
│   ├── search.ts           # V1 text scan over JSONL
│   └── actions.ts          # Tag/action command handlers
├── health/
│   └── diagnose.ts         # Health checks + conflict warning
└── (existing files unchanged)
```

### 2.2 Module Responsibilities

| Module | Primary Responsibility |
|--------|------------------------|
| `participant.ts` | Chat handler, LLM interaction, **tool result feedback loop** |
| `journal.ts` | File I/O, session lifecycle, event writing, **truncation handling** |
| `journalTypes.ts` | Type definitions (no runtime code) |
| `search.ts` | JSONL scanning and result formatting |
| `actions.ts` | Command handlers for tagging and actions |
| `diagnose.ts` | Health checks, **configurable conflict extension detection** |

---

## 3. Journal Storage Architecture

### 3.1 Directory Structure

```
<workspace-root>/
└── .ck3raven/
    └── chats/
        └── YYYY-MM-DD/
            └── session_<session_id>.jsonl
```

### 3.2 Storage Rules

| Rule | Description |
|------|-------------|
| **Location** | Workspace root (`.ck3raven/chats/`) |
| **Session ID format** | `ck3raven-YYYYMMDD-<uuid-suffix>` |
| **File format** | JSONL (newline-delimited JSON) |
| **Constraint** | **Append-only** - never rewrite existing lines |
| **ID generation** | `crypto.randomUUID()` with fallback (no external dependency) |

### 3.3 UUID Generation (Q7)

**No external dependency.** Use Node's built-in crypto:

```typescript
function generateUUID(): string {
    try {
        return crypto.randomUUID();
    } catch {
        // Fallback for older Node versions
        return `${Date.now().toString(36)}-${crypto.randomBytes(8).toString('hex')}`;
    }
}
```

### 3.4 Size Limit Handling (Q6)

**Hard rule: NEVER throw due to size. Always write a valid JSON line.**

| Condition | Action |
|-----------|--------|
| Field < 5MB | Store full content |
| Field ≥ 5MB | Truncate with metadata |

**Truncation metadata structure:**

```typescript
interface TruncationInfo {
    truncated: true;
    byte_len: number;
    sha256: string;
    preview: string;  // First 1000 chars
}
```

**Fields subject to truncation:**
- `assistant.text`
- `tool.input` (when serialized)
- `tool.result.reply` (when serialized)

### 3.5 Event Types

All events share base fields. See [Appendix A](#appendix-a-full-type-definitions) for complete schemas.

| Event Type | Purpose |
|------------|---------|
| `session_start` | Opens a new session |
| `turn` | User prompt + assistant response |
| `tool_call` | Each MCP tool invocation with result |
| `tag` | Tags applied to a turn |
| `action` | Follow-up action created |
| `health` | Diagnostic snapshot |

---

## 4. Participant Handler Design

### 4.1 Tool Orchestration (Q1)

**Decision:** Option A - Direct `vscode.lm.invokeTool` with result feedback loop.

**The handler MUST implement a proper tool loop:**

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Send messages to LLM with tools list                        │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Process response stream                                     │
│     ├── TextPart → stream to user                               │
│     └── ToolCallPart → execute tool, log, collect result        │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. If tool calls occurred:                                     │
│     ├── Append Assistant message with ToolCallParts             │
│     ├── Append User message with ToolResultParts                │
│     └── LOOP BACK to step 1 (continue conversation)             │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. When no more tool calls: finalize response                  │
│     └── Write turn event with complete assistant text           │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 System Prompt (Q5 - FINAL)

**Decision:** Minimal prompt ONLY. Do NOT embed mode documents.

```typescript
private getSystemPrompt(): string {
    return `You are ck3raven.
Use the provided tools when needed.
Tool names are dynamic; use EXACT tool name strings provided in tool list for this request.`;
}
```

**This is the ONLY system prompt. No alternatives. No dynamic expansion.**

### 4.3 Tool Set Filtering (Q4)

**Conservative filter** - Only expose tools matching the MCP namespace for this instance:

```typescript
private getMcpTools(): vscode.LanguageModelChatTool[] {
    const allTools = vscode.lm.tools;
    
    // Conservative filter: only ck3_* tools from our MCP server
    return allTools.filter(tool => 
        tool.name.includes('ck3_') || tool.name.includes('ck3lens')
    );
}
```

---

## 5. Implementation Phases

### Phase 5.1: Journal Foundation

**Files:** `src/chat/journal.ts`, `src/chat/journalTypes.ts`

```typescript
// src/chat/journalTypes.ts

import * as crypto from 'crypto';

/**
 * Schema version for journal events.
 * Increment when making breaking changes to event structure.
 */
export const JOURNAL_SCHEMA_VERSION = 1;

/**
 * Size limit for individual fields before truncation (5MB)
 */
export const FIELD_SIZE_LIMIT_BYTES = 5 * 1024 * 1024;

/**
 * Preview length for truncated fields
 */
export const TRUNCATION_PREVIEW_LENGTH = 1000;

/**
 * Workspace information included in every event
 */
export interface WorkspaceInfo {
    name: string;
    uri: string;
    trusted: boolean;
}

/**
 * Agent mode information
 */
export interface ModeInfo {
    agent_mode: 'ck3lens' | 'ck3raven-dev' | null;
    safety: 'safe';
}

/**
 * Base fields for all journal events
 */
export interface JournalEventBase {
    schema_version: typeof JOURNAL_SCHEMA_VERSION;
    event_id: string;
    event_type: string;
    timestamp: string;
    workspace: WorkspaceInfo;
    session_id: string;
    mode: ModeInfo;
}

/**
 * Truncation metadata when field exceeds size limit (Q6)
 */
export interface TruncationInfo {
    truncated: true;
    byte_len: number;
    sha256: string;
    preview: string;
}

/**
 * Session start event
 */
export interface SessionStartEvent extends JournalEventBase {
    event_type: 'session_start';
    session_title?: string;
    chat_surface: 'vscode.chat';
    participant: 'ck3raven';
}

/**
 * Turn event - one user prompt + assistant response
 */
export interface TurnEvent extends JournalEventBase {
    event_type: 'turn';
    turn_id: string;
    user: {
        text: string | TruncationInfo;
        selection_context?: string;
    };
    assistant: {
        text: string | TruncationInfo;
        summary?: string;
    };
    tool_call_count: number;
}

/**
 * Tool call event
 */
export interface ToolCallEvent extends JournalEventBase {
    event_type: 'tool_call';
    turn_id: string;
    tool: {
        name: string;
        input: Record<string, unknown> | TruncationInfo;
    };
    result: {
        ok: boolean;
        reply?: Record<string, unknown> | TruncationInfo;
        error?: string;
    };
    timing_ms: number;
}

/**
 * Tag event
 */
export interface TagEvent extends JournalEventBase {
    event_type: 'tag';
    turn_id: string;
    tags: string[];
    note?: string;
}

/**
 * Action event
 */
export interface ActionEvent extends JournalEventBase {
    event_type: 'action';
    action_id: string;
    turn_id: string;
    title: string;
    status: 'open' | 'in_progress' | 'done' | 'cancelled';
    details?: string;
    tags?: string[];
}

/**
 * Health check event
 */
export interface HealthEvent extends JournalEventBase {
    event_type: 'health';
    checks: {
        participant_registered: boolean;
        journal_writable: boolean;
        mcp_tools_registered: boolean;  // Renamed from mcp_reachable (accuracy)
        known_conflicts: string[];
    };
}

/**
 * Union of all journal event types
 */
export type JournalEvent = 
    | SessionStartEvent
    | TurnEvent
    | ToolCallEvent
    | TagEvent
    | ActionEvent
    | HealthEvent;
```

```typescript
// src/chat/journal.ts

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import { 
    JournalEvent, 
    SessionStartEvent, 
    TurnEvent, 
    ToolCallEvent,
    TagEvent,
    ActionEvent,
    HealthEvent,
    TruncationInfo,
    JOURNAL_SCHEMA_VERSION,
    FIELD_SIZE_LIMIT_BYTES,
    TRUNCATION_PREVIEW_LENGTH
} from './journalTypes';
import { Logger } from '../utils/logger';

/**
 * Generate UUID without external dependency (Q7)
 */
function generateUUID(): string {
    try {
        return crypto.randomUUID();
    } catch {
        // Fallback for older Node versions
        return `${Date.now().toString(36)}-${crypto.randomBytes(8).toString('hex')}`;
    }
}

/**
 * Apply truncation if content exceeds size limit (Q6)
 * NEVER throws - always returns valid data
 */
function applyTruncation(content: unknown): unknown | TruncationInfo {
    try {
        const json = typeof content === 'string' ? content : JSON.stringify(content);
        const byteLen = Buffer.byteLength(json, 'utf8');
        
        if (byteLen <= FIELD_SIZE_LIMIT_BYTES) {
            return content;
        }
        
        // Truncate with metadata
        return {
            truncated: true,
            byte_len: byteLen,
            sha256: crypto.createHash('sha256').update(json).digest('hex'),
            preview: json.slice(0, TRUNCATION_PREVIEW_LENGTH)
        } as TruncationInfo;
    } catch {
        // Even if hashing fails, return a safe truncation
        return {
            truncated: true,
            byte_len: -1,
            sha256: 'hash_failed',
            preview: String(content).slice(0, TRUNCATION_PREVIEW_LENGTH)
        } as TruncationInfo;
    }
}

export class JournalWriter implements vscode.Disposable {
    private sessionId: string | null = null;
    private sessionFilePath: string | null = null;
    private turnCounter: number = 0;
    private actionCounter: number = 0;
    private lastTurnId: string | null = null;
    private inMemoryBuffer: JournalEvent[] = [];
    private readonly MAX_BUFFER_SIZE = 50;

    constructor(private readonly logger: Logger) {}

    /**
     * Ensure a session is active, creating one if needed
     */
    async ensureSession(): Promise<string> {
        if (this.sessionId) {
            return this.sessionId;
        }

        const date = new Date();
        const dateStr = date.toISOString().slice(0, 10).replace(/-/g, '');
        
        // Use crypto.randomUUID() with fallback - no external dependency (Q7)
        const shortId = generateUUID().slice(0, 8);
        this.sessionId = `ck3raven-${dateStr}-${shortId}`;
        
        // Create session directory
        const sessionDir = await this.ensureSessionDir(date);
        this.sessionFilePath = path.join(sessionDir, `session_${this.sessionId}.jsonl`);
        
        // Write session_start event
        const event: SessionStartEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'session_start',
            timestamp: date.toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId,
            mode: await this.getCurrentMode(),
            chat_surface: 'vscode.chat',
            participant: 'ck3raven'
        };
        
        await this.appendEvent(event);
        
        return this.sessionId;
    }

    /**
     * Create turn ID and return it
     */
    createTurnId(): string {
        this.turnCounter++;
        const turnId = `t${String(this.turnCounter).padStart(4, '0')}`;
        this.lastTurnId = turnId;
        return turnId;
    }

    /**
     * Get the last turn ID for tagging
     */
    getLastTurnId(): string | null {
        return this.lastTurnId;
    }

    /**
     * Log a complete turn (with truncation for large content - Q6)
     */
    async logTurn(
        turnId: string,
        userText: string,
        assistantText: string,
        toolCallCount: number
    ): Promise<void> {
        const event: TurnEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'turn',
            timestamp: new Date().toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId!,
            mode: await this.getCurrentMode(),
            turn_id: turnId,
            user: {
                text: applyTruncation(userText) as string | TruncationInfo
            },
            assistant: {
                text: applyTruncation(assistantText) as string | TruncationInfo
            },
            tool_call_count: toolCallCount
        };
        
        await this.appendEvent(event);
    }

    /**
     * Log a tool call with size limit handling (Q6)
     * NEVER throws due to size
     */
    async logToolCall(
        turnId: string,
        toolCall: {
            name: string;
            input: Record<string, unknown>;
            result: { ok: boolean; reply?: unknown; error?: string };
            timing_ms: number;
        }
    ): Promise<void> {
        // Strip instance prefix from tool name for readability
        const cleanName = toolCall.name.replace(/^mcp_ck3_lens_[^_]+_/, '');
        
        // Apply truncation to input and result (Q6 - never fail)
        const truncatedInput = applyTruncation(toolCall.input);
        const truncatedReply = toolCall.result.reply 
            ? applyTruncation(toolCall.result.reply)
            : undefined;
        
        const event: ToolCallEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'tool_call',
            timestamp: new Date().toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId!,
            mode: await this.getCurrentMode(),
            turn_id: turnId,
            tool: {
                name: cleanName,
                input: truncatedInput as Record<string, unknown> | TruncationInfo
            },
            result: {
                ok: toolCall.result.ok,
                reply: truncatedReply as Record<string, unknown> | TruncationInfo | undefined,
                error: toolCall.result.error
            },
            timing_ms: toolCall.timing_ms
        };
        
        await this.appendEvent(event);
    }

    /**
     * Log a tag applied to a turn
     */
    async logTag(turnId: string, tags: string[], note?: string): Promise<void> {
        const event: TagEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'tag',
            timestamp: new Date().toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId!,
            mode: await this.getCurrentMode(),
            turn_id: turnId,
            tags,
            note
        };
        
        await this.appendEvent(event);
    }

    /**
     * Log an action created from a turn
     */
    async logAction(
        turnId: string,
        title: string,
        details?: string,
        tags?: string[]
    ): Promise<string> {
        this.actionCounter++;
        const actionId = `a${String(this.actionCounter).padStart(4, '0')}`;
        
        const event: ActionEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'action',
            timestamp: new Date().toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId!,
            mode: await this.getCurrentMode(),
            action_id: actionId,
            turn_id: turnId,
            title,
            status: 'open',
            details,
            tags
        };
        
        await this.appendEvent(event);
        return actionId;
    }

    /**
     * Log a health check result
     */
    async logHealth(checks: HealthEvent['checks']): Promise<void> {
        // Ensure we have a session for health logging
        await this.ensureSession();
        
        const event: HealthEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'health',
            timestamp: new Date().toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId!,
            mode: await this.getCurrentMode(),
            checks
        };
        
        await this.appendEvent(event);
    }

    /**
     * Append an event to the journal file
     * CRITICAL: Never fail - buffer in memory if file write fails (Q6 spirit)
     */
    private async appendEvent(event: JournalEvent): Promise<void> {
        if (!this.sessionFilePath) {
            this.bufferEvent(event);
            return;
        }
        
        try {
            const line = JSON.stringify(event) + '\n';
            await fs.promises.appendFile(this.sessionFilePath, line, 'utf8');
            
            // Flush any buffered events
            await this.flushBuffer();
            
        } catch (error) {
            this.logger.error('Failed to write journal event', error);
            this.bufferEvent(event);
        }
    }

    /**
     * Buffer event in memory if file write fails
     */
    private bufferEvent(event: JournalEvent): void {
        this.inMemoryBuffer.push(event);
        
        // Keep buffer bounded
        if (this.inMemoryBuffer.length > this.MAX_BUFFER_SIZE) {
            this.inMemoryBuffer.shift();
        }
        
        this.logger.warn(`Buffered journal event (${this.inMemoryBuffer.length} in buffer)`);
    }

    /**
     * Try to flush buffered events to file
     */
    private async flushBuffer(): Promise<void> {
        if (this.inMemoryBuffer.length === 0 || !this.sessionFilePath) {
            return;
        }
        
        const toFlush = [...this.inMemoryBuffer];
        this.inMemoryBuffer = [];
        
        for (const event of toFlush) {
            try {
                const line = JSON.stringify(event) + '\n';
                await fs.promises.appendFile(this.sessionFilePath, line, 'utf8');
            } catch {
                this.inMemoryBuffer.push(event);
            }
        }
    }

    /**
     * Ensure the session directory exists
     */
    private async ensureSessionDir(date: Date): Promise<string> {
        const workspaceRoot = this.getWorkspaceRoot();
        if (!workspaceRoot) {
            throw new Error('No workspace folder found');
        }
        
        const dateFolder = date.toISOString().slice(0, 10); // YYYY-MM-DD
        const sessionDir = path.join(workspaceRoot, '.ck3raven', 'chats', dateFolder);
        
        await fs.promises.mkdir(sessionDir, { recursive: true });
        
        return sessionDir;
    }

    /**
     * Get workspace root path
     */
    private getWorkspaceRoot(): string | undefined {
        return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    }

    /**
     * Get workspace info for events
     */
    private getWorkspaceInfo(): { name: string; uri: string; trusted: boolean } {
        const folders = vscode.workspace.workspaceFolders;
        const folder = folders?.[0];
        
        return {
            name: folder?.name || 'unknown',
            uri: folder?.uri.toString() || '',
            trusted: vscode.workspace.isTrusted
        };
    }

    /**
     * Get current agent mode
     */
    private async getCurrentMode(): Promise<{ agent_mode: 'ck3lens' | 'ck3raven-dev' | null; safety: 'safe' }> {
        // Read from MCP mode file if available
        // For V1, return null if not initialized
        return {
            agent_mode: null,
            safety: 'safe'
        };
    }

    /**
     * Check if journal is writable
     */
    async isWritable(): Promise<boolean> {
        try {
            const workspaceRoot = this.getWorkspaceRoot();
            if (!workspaceRoot) {
                return false;
            }
            
            const testDir = path.join(workspaceRoot, '.ck3raven', 'chats');
            await fs.promises.mkdir(testDir, { recursive: true });
            
            const testFile = path.join(testDir, '.write_test');
            await fs.promises.writeFile(testFile, 'test', 'utf8');
            await fs.promises.unlink(testFile);
            
            return true;
        } catch {
            return false;
        }
    }

    /**
     * Get buffer status for diagnostics
     */
    getBufferStatus(): { count: number; maxSize: number } {
        return {
            count: this.inMemoryBuffer.length,
            maxSize: this.MAX_BUFFER_SIZE
        };
    }

    dispose(): void {
        // Flush any remaining buffer on dispose
        if (this.sessionFilePath && this.inMemoryBuffer.length > 0) {
            const lines = this.inMemoryBuffer.map(e => JSON.stringify(e)).join('\n') + '\n';
            try {
                fs.appendFileSync(this.sessionFilePath, lines, 'utf8');
            } catch {
                this.logger.error('Failed to flush journal buffer on dispose');
            }
        }
    }
}
```

### Phase 5.2: Participant Handler

**File:** `src/chat/participant.ts`

```typescript
// src/chat/participant.ts

import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { JournalWriter } from './journal';
import { Logger } from '../utils/logger';

export class Ck3RavenParticipant implements vscode.Disposable {
    private participant: vscode.ChatParticipant;
    private journal: JournalWriter;
    private disposables: vscode.Disposable[] = [];

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger
    ) {
        this.journal = new JournalWriter(logger);
        
        // Register the chat participant
        this.participant = vscode.chat.createChatParticipant(
            'ck3raven',
            this.handleRequest.bind(this)
        );
        
        // Set participant properties
        this.participant.iconPath = vscode.Uri.joinPath(
            context.extensionUri, 
            'media', 
            'ck3raven-icon.png'
        );
        
        // Set up followup provider
        this.participant.followupProvider = {
            provideFollowups: this.provideFollowups.bind(this)
        };
        
        // Subscribe to feedback events
        this.disposables.push(
            this.participant.onDidReceiveFeedback(this.handleFeedback.bind(this))
        );
    }

    /**
     * Expose journal for command registration
     */
    public getJournal(): JournalWriter {
        return this.journal;
    }

    /**
     * Main request handler - implements tool result feedback loop (Q1)
     */
    private async handleRequest(
        request: vscode.ChatRequest,
        context: vscode.ChatContext,
        stream: vscode.ChatResponseStream,
        token: vscode.CancellationToken
    ): Promise<vscode.ChatResult> {
        // Ensure session is started
        await this.journal.ensureSession();
        
        // Create turn ID
        const turnId = this.journal.createTurnId();
        const userText = request.prompt;
        
        // Count tool calls for this turn
        let toolCallCount = 0;
        
        try {
            // Build initial messages
            const messages = this.buildMessages(request, context);
            
            // Get available MCP tools (Q4 - conservative filter)
            const tools = this.getMcpTools();
            
            // Full response text accumulator
            let fullResponseText = '';
            
            // Tool orchestration loop - continues until no more tool calls (Q1)
            let continueLoop = true;
            while (continueLoop && !token.isCancellationRequested) {
                continueLoop = false;
                
                // Send request to LLM
                const response = await request.model.sendRequest(
                    messages,
                    { tools },
                    token
                );
                
                // Collect tool calls from this iteration
                const iterationToolCalls: vscode.LanguageModelToolCallPart[] = [];
                const iterationToolResults: Array<{ callId: string; result: unknown }> = [];
                
                // Process response stream
                for await (const part of response.stream) {
                    if (token.isCancellationRequested) break;
                    
                    if (part instanceof vscode.LanguageModelTextPart) {
                        // Stream text to user
                        stream.markdown(part.value);
                        fullResponseText += part.value;
                        
                    } else if (part instanceof vscode.LanguageModelToolCallPart) {
                        // Collect tool call for batch processing
                        iterationToolCalls.push(part);
                    }
                }
                
                // Execute all tool calls from this iteration
                if (iterationToolCalls.length > 0) {
                    continueLoop = true; // Need another LLM round after tools
                    
                    for (const toolCall of iterationToolCalls) {
                        toolCallCount++;
                        const startTime = Date.now();
                        
                        try {
                            // Show progress
                            stream.progress(`Calling ${this.cleanToolName(toolCall.name)}...`);
                            
                            // Execute the tool via vscode.lm.invokeTool (Q1)
                            const result = await vscode.lm.invokeTool(
                                toolCall.name,
                                {
                                    input: toolCall.input,
                                    toolInvocationToken: request.toolInvocationToken
                                },
                                token
                            );
                            
                            const timing = Date.now() - startTime;
                            
                            // Log successful tool call to journal
                            await this.journal.logToolCall(turnId, {
                                name: toolCall.name,
                                input: toolCall.input as Record<string, unknown>,
                                result: { ok: true, reply: result },
                                timing_ms: timing
                            });
                            
                            // Collect result for feedback to LLM
                            iterationToolResults.push({
                                callId: toolCall.callId,
                                result: result
                            });
                            
                        } catch (error) {
                            const timing = Date.now() - startTime;
                            
                            // Log failed tool call to journal
                            await this.journal.logToolCall(turnId, {
                                name: toolCall.name,
                                input: toolCall.input as Record<string, unknown>,
                                result: { ok: false, error: String(error) },
                                timing_ms: timing
                            });
                            
                            // Still provide error result to LLM
                            iterationToolResults.push({
                                callId: toolCall.callId,
                                result: { error: String(error) }
                            });
                        }
                    }
                    
                    // CRITICAL: Feed tool results back to LLM (Q1 requirement)
                    // Append assistant message with tool calls
                    messages.push(
                        vscode.LanguageModelChatMessage.Assistant(
                            iterationToolCalls.map(tc => 
                                new vscode.LanguageModelToolCallPart(tc.callId, tc.name, tc.input)
                            )
                        )
                    );
                    
                    // Append user message with tool results
                    messages.push(
                        vscode.LanguageModelChatMessage.User(
                            iterationToolResults.map(tr =>
                                new vscode.LanguageModelToolResultPart(tr.callId, tr.result)
                            )
                        )
                    );
                }
            }
            
            // Log the complete turn
            await this.journal.logTurn(turnId, userText, fullResponseText, toolCallCount);
            
            return {
                metadata: {
                    turnId,
                    toolCallCount
                }
            };
            
        } catch (error) {
            this.logger.error('Chat request failed', error);
            stream.markdown(`\n\n⚠️ Error: ${error}`);
            
            // Still log the turn (with error)
            await this.journal.logTurn(turnId, userText, `Error: ${error}`, toolCallCount);
            
            return {
                errorDetails: {
                    message: String(error)
                }
            };
        }
    }

    /**
     * Build messages array for LLM request
     */
    private buildMessages(
        request: vscode.ChatRequest,
        context: vscode.ChatContext
    ): vscode.LanguageModelChatMessage[] {
        const messages: vscode.LanguageModelChatMessage[] = [];
        
        // System prompt as first user message (prefixed for clarity)
        // Note: VS Code LM API may not have dedicated system role
        messages.push(
            vscode.LanguageModelChatMessage.User(`SYSTEM: ${this.getSystemPrompt()}`)
        );
        
        // Add conversation history
        for (const turn of context.history) {
            if (turn instanceof vscode.ChatRequestTurn) {
                messages.push(
                    vscode.LanguageModelChatMessage.User(turn.prompt)
                );
            } else if (turn instanceof vscode.ChatResponseTurn) {
                const text = this.extractResponseText(turn);
                messages.push(
                    vscode.LanguageModelChatMessage.Assistant(text)
                );
            }
        }
        
        // Add current prompt
        messages.push(
            vscode.LanguageModelChatMessage.User(request.prompt)
        );
        
        return messages;
    }

    /**
     * Minimal system prompt (Q5 - FINAL)
     * This is the ONLY system prompt. No alternatives. No dynamic expansion.
     */
    private getSystemPrompt(): string {
        return `You are ck3raven.
Use the provided tools when needed.
Tool names are dynamic; use EXACT tool name strings provided in tool list for this request.`;
    }

    /**
     * Get MCP tools available for this request (Q4 - conservative filter)
     */
    private getMcpTools(): vscode.LanguageModelChatTool[] {
        const allTools = vscode.lm.tools;
        
        // Conservative filter: only ck3_* tools from our MCP server
        return allTools.filter(tool => 
            tool.name.includes('ck3_') || tool.name.includes('ck3lens')
        );
    }

    /**
     * Clean tool name for display (strip instance prefix)
     */
    private cleanToolName(toolName: string): string {
        return toolName.replace(/^mcp_ck3_lens_[^_]+_/, '');
    }

    /**
     * Extract text from a response turn
     */
    private extractResponseText(turn: vscode.ChatResponseTurn): string {
        let text = '';
        for (const part of turn.response) {
            if (part instanceof vscode.ChatResponseMarkdownPart) {
                text += part.value.value;
            }
        }
        return text;
    }

    /**
     * Provide followup suggestions
     */
    private provideFollowups(
        result: vscode.ChatResult,
        context: vscode.ChatContext,
        token: vscode.CancellationToken
    ): vscode.ProviderResult<vscode.ChatFollowup[]> {
        return [
            {
                prompt: 'Show me more details',
                label: 'More details'
            },
            {
                prompt: 'Search for related symbols',
                label: 'Find related'
            }
        ];
    }

    /**
     * Handle user feedback on responses
     */
    private handleFeedback(feedback: vscode.ChatResultFeedback): void {
        this.logger.info(`Received feedback: ${feedback.kind}`);
    }

    dispose(): void {
        this.participant.dispose();
        this.journal.dispose();
        this.disposables.forEach(d => d.dispose());
    }
}
```

### Phase 5.3: Health & Diagnostics

**File:** `src/health/diagnose.ts`

```typescript
// src/health/diagnose.ts

import * as vscode from 'vscode';
import { JournalWriter } from '../chat/journal';
import { Logger } from '../utils/logger';

export interface HealthCheckResult {
    participant_registered: boolean;
    journal_writable: boolean;
    mcp_tools_registered: boolean;  // Renamed from mcp_reachable (accuracy)
    known_conflicts: string[];
}

export class DiagnosticsService {
    constructor(
        private readonly journal: JournalWriter,
        private readonly logger: Logger
    ) {}

    /**
     * Run all health checks
     */
    async runChecks(): Promise<HealthCheckResult> {
        const result: HealthCheckResult = {
            participant_registered: this.checkParticipant(),
            journal_writable: await this.checkJournal(),
            mcp_tools_registered: this.checkMcpToolsRegistered(),
            known_conflicts: this.checkConflicts()
        };

        // Log health event to journal
        await this.journal.logHealth(result);

        return result;
    }

    /**
     * Check if participant is registered
     */
    private checkParticipant(): boolean {
        // If this code is running, participant is registered
        return true;
    }

    /**
     * Check if journal is writable
     */
    private async checkJournal(): Promise<boolean> {
        return this.journal.isWritable();
    }

    /**
     * Check if MCP tools are registered (renamed from "reachable" for accuracy)
     * This checks if tools exist, not if server responds to ping
     */
    private checkMcpToolsRegistered(): boolean {
        try {
            const tools = vscode.lm.tools;
            return tools.some(t => 
                t.name.includes('ck3_') || t.name.includes('ck3lens')
            );
        } catch {
            return false;
        }
    }

    /**
     * Check for known conflicting extensions (Q3)
     * Uses configurable setting with empty default
     */
    private checkConflicts(): string[] {
        const config = vscode.workspace.getConfiguration('ck3raven');
        const knownConflicts = config.get<string[]>('chatJournal.knownChatRecorderExtensions', []);
        
        const foundConflicts: string[] = [];
        
        for (const extId of knownConflicts) {
            const ext = vscode.extensions.getExtension(extId);
            if (ext) {
                foundConflicts.push(extId);
            }
        }
        
        return foundConflicts;
    }
}

/**
 * Register diagnose command
 */
export function registerDiagnoseCommand(
    context: vscode.ExtensionContext,
    journal: JournalWriter,
    logger: Logger
): void {
    const diagnostics = new DiagnosticsService(journal, logger);
    const outputChannel = vscode.window.createOutputChannel('CK3 Raven Diagnostics');
    
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.diagnose', async () => {
            outputChannel.clear();
            outputChannel.appendLine('CK3 Raven Health Check');
            outputChannel.appendLine('='.repeat(40));
            outputChannel.appendLine('');
            
            const result = await diagnostics.runChecks();
            
            // Participant
            const partStatus = result.participant_registered ? '✅' : '❌';
            outputChannel.appendLine(`${partStatus} Participant: ${result.participant_registered ? 'Registered' : 'NOT REGISTERED'}`);
            
            // Journal
            const journalStatus = result.journal_writable ? '✅' : '❌';
            outputChannel.appendLine(`${journalStatus} Journal: ${result.journal_writable ? 'Writable' : 'NOT WRITABLE'}`);
            
            // Buffer status
            const bufferStatus = journal.getBufferStatus();
            if (bufferStatus.count > 0) {
                outputChannel.appendLine(`   ⚠️ Buffered events: ${bufferStatus.count}/${bufferStatus.maxSize}`);
            }
            
            // MCP Tools (renamed from "reachable")
            const mcpStatus = result.mcp_tools_registered ? '✅' : '❌';
            outputChannel.appendLine(`${mcpStatus} MCP Tools: ${result.mcp_tools_registered ? 'Registered' : 'NOT REGISTERED'}`);
            
            // Conflicts (Q3 - warn only, never block)
            if (result.known_conflicts.length > 0) {
                outputChannel.appendLine(`⚠️ Potential Conflicts Detected:`);
                for (const extId of result.known_conflicts) {
                    outputChannel.appendLine(`   - ${extId}`);
                }
            } else {
                outputChannel.appendLine(`✅ Conflicts: None detected`);
            }
            
            outputChannel.appendLine('');
            outputChannel.appendLine('Health check complete.');
            
            outputChannel.show();
        })
    );
    
    // Also check conflicts on activation (warn only)
    const conflicts = diagnostics['checkConflicts']();
    if (conflicts.length > 0) {
        logger.warn(`Potential chat recorder conflicts detected: ${conflicts.join(', ')}`);
    }
}
```

### Phase 5.4: Commands (Tag/Action)

**File:** `src/chat/actions.ts`

```typescript
// src/chat/actions.ts

import * as vscode from 'vscode';
import { JournalWriter } from './journal';
import { Logger } from '../utils/logger';

// Common tags for quick selection
const COMMON_TAGS = [
    'todo',
    'bug',
    'feature',
    'documentation',
    'research',
    'conflict',
    'trait',
    'event',
    'decision',
    'on_action',
    'localization'
];

export function registerJournalCommands(
    context: vscode.ExtensionContext,
    journal: JournalWriter,
    logger: Logger
): void {
    
    // Tag Last Turn
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.chatJournal.tagLastTurn', async () => {
            const lastTurnId = journal.getLastTurnId();
            
            if (!lastTurnId) {
                vscode.window.showWarningMessage(
                    'No chat turn to tag. Start a conversation with @ck3raven first.'
                );
                return;
            }
            
            // Show multi-select quick pick
            const selected = await vscode.window.showQuickPick(
                COMMON_TAGS.map(tag => ({ label: tag, picked: false })),
                {
                    title: 'Tag Last Turn',
                    placeHolder: 'Select tags (or type custom tag and press Enter)',
                    canPickMany: true
                }
            );
            
            if (!selected || selected.length === 0) {
                return;
            }
            
            const tags = selected.map(s => s.label);
            
            // Optional note
            const note = await vscode.window.showInputBox({
                prompt: 'Add a note (optional)',
                placeHolder: 'Optional context for this tag'
            });
            
            await journal.logTag(lastTurnId, tags, note || undefined);
            
            vscode.window.showInformationMessage(
                `Tagged turn ${lastTurnId} with: ${tags.join(', ')}`
            );
        })
    );
    
    // Create Action from Last Turn
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.chatJournal.createActionFromLastTurn', async () => {
            const lastTurnId = journal.getLastTurnId();
            
            if (!lastTurnId) {
                vscode.window.showWarningMessage(
                    'No chat turn to create action from. Start a conversation with @ck3raven first.'
                );
                return;
            }
            
            // Get title
            const title = await vscode.window.showInputBox({
                title: 'Action Title',
                prompt: 'Brief description of the action',
                placeHolder: 'e.g., Fix brave trait conflict'
            });
            
            if (!title) {
                return;
            }
            
            // Get details
            const details = await vscode.window.showInputBox({
                title: 'Action Details',
                prompt: 'Detailed description (optional)',
                placeHolder: 'Steps to complete, context, etc.'
            });
            
            // Select tags
            const selectedTags = await vscode.window.showQuickPick(
                COMMON_TAGS.map(tag => ({ label: tag, picked: false })),
                {
                    title: 'Action Tags',
                    placeHolder: 'Select tags for this action (optional)',
                    canPickMany: true
                }
            );
            
            const tags = selectedTags?.map(s => s.label);
            
            const actionId = await journal.logAction(
                lastTurnId,
                title,
                details || undefined,
                tags
            );
            
            vscode.window.showInformationMessage(`Created action ${actionId}: ${title}`);
        })
    );
    
    // Open Journal Folder
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.chatJournal.openFolder', async () => {
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (!workspaceFolders) {
                vscode.window.showWarningMessage('No workspace open');
                return;
            }
            
            const journalPath = vscode.Uri.joinPath(
                workspaceFolders[0].uri,
                '.ck3raven',
                'chats'
            );
            
            await vscode.commands.executeCommand('revealFileInOS', journalPath);
        })
    );
}
```

### Phase 5.5: Search

**File:** `src/chat/search.ts`

```typescript
// src/chat/search.ts

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as readline from 'readline';
import { Logger } from '../utils/logger';

interface SearchResult {
    file: string;
    sessionId: string;
    date: string;
    turnId?: string;
    eventType: string;
    matchText: string;
    lineNumber: number;
}

export class JournalSearch {
    constructor(private readonly logger: Logger) {}

    /**
     * Search journal files for a query string
     */
    async search(query: string): Promise<SearchResult[]> {
        const workspaceRoot = this.getWorkspaceRoot();
        if (!workspaceRoot) {
            return [];
        }

        const chatsDir = path.join(workspaceRoot, '.ck3raven', 'chats');
        
        if (!fs.existsSync(chatsDir)) {
            return [];
        }

        const results: SearchResult[] = [];
        const queryLower = query.toLowerCase();

        // Scan all date folders
        const dateFolders = await fs.promises.readdir(chatsDir);
        
        for (const dateFolder of dateFolders) {
            const datePath = path.join(chatsDir, dateFolder);
            const stat = await fs.promises.stat(datePath);
            
            if (!stat.isDirectory()) continue;

            // Scan all session files
            const sessionFiles = await fs.promises.readdir(datePath);
            
            for (const sessionFile of sessionFiles) {
                if (!sessionFile.endsWith('.jsonl')) continue;
                
                const filePath = path.join(datePath, sessionFile);
                const sessionId = sessionFile.replace('session_', '').replace('.jsonl', '');
                
                const fileResults = await this.searchFile(
                    filePath,
                    queryLower,
                    sessionId,
                    dateFolder
                );
                
                results.push(...fileResults);
            }
        }

        return results;
    }

    private async searchFile(
        filePath: string,
        queryLower: string,
        sessionId: string,
        date: string
    ): Promise<SearchResult[]> {
        const results: SearchResult[] = [];
        
        const fileStream = fs.createReadStream(filePath);
        const rl = readline.createInterface({
            input: fileStream,
            crlfDelay: Infinity
        });

        let lineNumber = 0;
        
        for await (const line of rl) {
            lineNumber++;
            
            try {
                const event = JSON.parse(line);
                const searchableText = this.getSearchableText(event);
                
                if (searchableText.toLowerCase().includes(queryLower)) {
                    results.push({
                        file: filePath,
                        sessionId,
                        date,
                        turnId: event.turn_id,
                        eventType: event.event_type,
                        matchText: this.extractSnippet(searchableText, queryLower),
                        lineNumber
                    });
                }
            } catch {
                // Skip invalid JSON lines
            }
        }

        return results;
    }

    private getSearchableText(event: Record<string, unknown>): string {
        const parts: string[] = [];
        
        const user = event.user as { text?: string | { preview?: string } } | undefined;
        if (user?.text) {
            if (typeof user.text === 'string') {
                parts.push(user.text);
            } else if (user.text.preview) {
                parts.push(user.text.preview);
            }
        }
        
        const assistant = event.assistant as { text?: string | { preview?: string } } | undefined;
        if (assistant?.text) {
            if (typeof assistant.text === 'string') {
                parts.push(assistant.text);
            } else if (assistant.text.preview) {
                parts.push(assistant.text.preview);
            }
        }
        
        const tags = event.tags as string[] | undefined;
        if (tags) parts.push(tags.join(' '));
        
        if (typeof event.title === 'string') parts.push(event.title);
        if (typeof event.details === 'string') parts.push(event.details);
        
        const tool = event.tool as { name?: string } | undefined;
        if (tool?.name) parts.push(tool.name);
        
        return parts.join(' ');
    }

    private extractSnippet(text: string, query: string): string {
        const index = text.toLowerCase().indexOf(query);
        if (index === -1) return text.slice(0, 100);
        
        const start = Math.max(0, index - 40);
        const end = Math.min(text.length, index + query.length + 40);
        
        let snippet = text.slice(start, end);
        if (start > 0) snippet = '...' + snippet;
        if (end < text.length) snippet = snippet + '...';
        
        return snippet;
    }

    private getWorkspaceRoot(): string | undefined {
        return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    }
}

/**
 * Register search command
 */
export function registerSearchCommand(
    context: vscode.ExtensionContext,
    logger: Logger
): void {
    const searcher = new JournalSearch(logger);
    const outputChannel = vscode.window.createOutputChannel('CK3 Raven Journal Search');
    
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.chatJournal.search', async () => {
            const query = await vscode.window.showInputBox({
                title: 'Search Chat Journal',
                prompt: 'Enter search term',
                placeHolder: 'e.g., brave trait, conflict, todo'
            });
            
            if (!query) return;
            
            outputChannel.clear();
            outputChannel.appendLine(`Searching for: "${query}"`);
            outputChannel.appendLine('='.repeat(60));
            
            const results = await searcher.search(query);
            
            if (results.length === 0) {
                outputChannel.appendLine('\nNo results found.');
            } else {
                outputChannel.appendLine(`\nFound ${results.length} result(s):\n`);
                
                for (const result of results) {
                    outputChannel.appendLine(`📅 ${result.date} | Session: ${result.sessionId}`);
                    outputChannel.appendLine(`   Type: ${result.eventType}${result.turnId ? ` | Turn: ${result.turnId}` : ''}`);
                    outputChannel.appendLine(`   Match: ${result.matchText}`);
                    outputChannel.appendLine(`   File: ${result.file}:${result.lineNumber}`);
                    outputChannel.appendLine('');
                }
            }
            
            outputChannel.show();
        })
    );
}
```

### Phase 5.6: Extension Integration

**Updates to:** `src/extension.ts`

```typescript
// Add imports at top of extension.ts
import { Ck3RavenParticipant } from './chat/participant';
import { registerJournalCommands } from './chat/actions';
import { registerSearchCommand } from './chat/search';
import { registerDiagnoseCommand } from './health/diagnose';

// In activate() function, after other initialization:

// Initialize Chat Participant
const chatParticipant = new Ck3RavenParticipant(context, logger);
context.subscriptions.push(chatParticipant);

// Register journal commands (uses participant's journal instance)
registerJournalCommands(context, chatParticipant.getJournal(), logger);

// Register search command
registerSearchCommand(context, logger);

// Register diagnose command (checks conflicts on activation too)
registerDiagnoseCommand(context, chatParticipant.getJournal(), logger);

logger.info('ck3raven chat participant registered');
```

---

## 6. Non-Negotiable Acceptance Tests

**These MUST pass before PR can be submitted.**

| # | Test | Verification |
|---|------|--------------|
| 1 | `@ck3raven hello` returns response; Status shows Participant ✅ | Type in chat, verify response appears |
| 2 | After one message: JSONL exists at `.ck3raven/chats/YYYY-MM-DD/session_*.jsonl` with `session_start` + `turn` events | Check filesystem |
| 3 | Append-only: Second message adds new lines, does not rewrite | Send 2 messages, verify file grows |
| 4 | Tool call prompt triggers `tool_call` event with tool name, input, and output (full or truncated per Q6) | Use a prompt that triggers tool use, verify event |
| 5 | `ck3raven.chatJournal.tagLastTurn` writes `tag` event | Run command, check JSONL |
| 6 | `ck3raven.chatJournal.createActionFromLastTurn` writes `action` event | Run command, check JSONL |
| 7 | `ck3raven.chatJournal.search` finds known word and prints session/turn info | Search for word in existing journal |
| 8 | Conflict warning: When extension in `knownChatRecorderExtensions` is enabled, diagnose shows ⚠️ and prints IDs | Configure setting, run diagnose |

### Manual Test Procedure

```
1. Open VS Code with ck3raven workspace
2. Open Chat panel
3. Type: @ck3raven hello
4. Verify response appears
5. Check .ck3raven/chats/ exists with JSONL file
6. Type: @ck3raven search for the brave trait
7. Verify tool_call event in JSONL has tool name, input, result
8. Run command: CK3 Raven: Tag Last Chat Turn
9. Select tags, verify tag event in JSONL
10. Run command: CK3 Raven: Create Action from Last Turn
11. Enter title, verify action event in JSONL
12. Run command: CK3 Raven: Search Chat Journal
13. Search for "brave", verify output shows results
14. Add extension ID to ck3raven.chatJournal.knownChatRecorderExtensions
15. Run command: CK3 Raven: Run Diagnostics
16. Verify ⚠️ Conflicts warning appears
```

---

## 7. Estimated Effort

| Phase | Files | Complexity | Est. Time |
|-------|-------|------------|-----------|
| 5.1 Journal Foundation | 2 files | Medium | 2-3 hours |
| 5.2 Participant (with tool loop) | 1 file | **High** | 4-5 hours |
| 5.3 Health & Diagnostics | 1 file | Low | 1 hour |
| 5.4 Commands (tag/action) | 1 file | Low | 1 hour |
| 5.5 Search | 1 file | Medium | 1-2 hours |
| 5.6 Extension Integration | Updates | Low | 1 hour |
| Acceptance Testing | — | Medium | 2-3 hours |
| **Total** | **6 new files** | — | **12-16 hours** |

---

## Implementation Order

```
Phase 5.1: Journal Foundation
    └── journalTypes.ts (types, size constants, TruncationInfo)
    └── journal.ts (writer with truncation handling, UUID fallback)
        ↓
Phase 5.2: Participant
    └── participant.ts (handler with tool feedback loop)
    └── package.json updates (chatParticipants, commands, settings)
        ↓
Phase 5.3: Diagnostics
    └── diagnose.ts (health checks, mcp_tools_registered, conflict detection)
        ↓
Phase 5.4: Commands
    └── actions.ts (tag, action, openFolder)
        ↓
Phase 5.5: Search
    └── search.ts (JSONL text scan with truncation-aware extraction)
        ↓
Phase 5.6: Integration
    └── extension.ts updates
        ↓
Acceptance Testing
    └── Run all 8 tests
    └── Fix any failures
```

---

## Appendix: Key Decisions Summary

| Decision | Implementation |
|----------|----------------|
| Q1: Tool orchestration | `vscode.lm.invokeTool` + `ToolResultPart` feedback loop |
| Q2: Session scope | Per-workspace, session IDs include workspace context |
| Q3: Journal location | `/.ck3raven/chats/YYYY-MM-DD/session_*.jsonl` |
| Q4: Tool filtering | Conservative: `includes('ck3_')` or `includes('ck3lens')` |
| Q5: System prompt | Minimal 3-line prompt only. No mode docs. |
| Q6: Size limits | Truncate with `sha256` + `byte_len` + `preview`. Never throw. |
| Q7: UUID | `crypto.randomUUID()` with `Date.now().toString(36)` fallback |
| MCP health | Renamed to `mcp_tools_registered` (checks tool existence) |

---

**APPROVED. Implementation may proceed.**
