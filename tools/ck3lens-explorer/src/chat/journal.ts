/**
 * Chat Journal Writer
 *
 * JSONL append-only journaling for @ck3raven chat participant.
 * V1 Brief compliance: workspace-local, never fail due to size (Q6).
 */

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
 * Generate UUID - requires Node 14.17+ / VS Code 1.96+
 * NO FALLBACK: If crypto.randomUUID is unavailable, fail loudly.
 */
function generateUUID(): string {
    if (typeof crypto.randomUUID !== 'function') {
        throw new Error('crypto.randomUUID not available - requires Node 14.17+ / VS Code 1.96+');
    }
    return crypto.randomUUID();
}

/**
 * Apply truncation if content exceeds size limit (Q6)
 * NO FALLBACK: If truncation/hashing fails, throw.
 */
function applyTruncation(content: unknown): unknown | TruncationInfo {
    const json = typeof content === 'string' ? content : JSON.stringify(content);
    const byteLen = Buffer.byteLength(json, 'utf8');

    if (byteLen <= FIELD_SIZE_LIMIT_BYTES) {
        return content;
    }

    // Truncate with metadata - no fallback on hash failure
    return {
        truncated: true,
        byte_len: byteLen,
        sha256: crypto.createHash('sha256').update(json).digest('hex'),
        preview: json.slice(0, TRUNCATION_PREVIEW_LENGTH)
    } as TruncationInfo;
}

export class JournalWriter implements vscode.Disposable {
    private sessionId: string | null = null;
    private sessionFilePath: string | null = null;
    private turnCounter: number = 0;
    private actionCounter: number = 0;
    private lastTurnId: string | null = null;

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
            mode: this.getCurrentMode(),
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
     * Get current session ID
     */
    getSessionId(): string | null {
        return this.sessionId;
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
            mode: this.getCurrentMode(),
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
            mode: this.getCurrentMode(),
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
     * Log a tag applied to current turn or session
     * @param tagOrTurnId - Either a tag string (uses last turn) or turn ID
     * @param tags - Array of tags (if first arg is turnId)
     * @param note - Optional note
     */
    async logTag(tagOrTurnId: string, tags?: string[] | string, note?: string): Promise<void> {
        await this.ensureSession();
        
        let turnId: string;
        let tagArray: string[];
        
        // Overload support: logTag("tag") or logTag(turnId, ["tags"])
        if (Array.isArray(tags)) {
            turnId = tagOrTurnId;
            tagArray = tags;
        } else if (typeof tags === 'string') {
            // logTag(turnId, "single_tag")
            turnId = tagOrTurnId;
            tagArray = [tags];
        } else {
            // logTag("tag") - uses last turn
            turnId = this.lastTurnId || 'session';
            tagArray = [tagOrTurnId];
        }

        const event: TagEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'tag',
            timestamp: new Date().toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId!,
            mode: this.getCurrentMode(),
            turn_id: turnId,
            tags: tagArray,
            note
        };

        await this.appendEvent(event);
    }

    /**
     * Log an action created from a turn
     * @param titleOrTurnId - Either action title (uses last turn) or turn ID
     * @param title - Title if first arg is turn ID
     * @param details - Optional details
     * @param tags - Optional tags
     */
    async logAction(
        titleOrTurnId: string,
        title?: string,
        details?: string | Record<string, unknown>,
        tags?: string[]
    ): Promise<string> {
        await this.ensureSession();
        
        let turnId: string;
        let actionTitle: string;
        let actionDetails: string | undefined;
        
        // Overload support: logAction("title") or logAction(turnId, "title")
        if (title !== undefined) {
            turnId = titleOrTurnId;
            actionTitle = title;
            actionDetails = typeof details === 'string' ? details : JSON.stringify(details);
        } else {
            // logAction("title", {payload}) form from actions.ts
            turnId = this.lastTurnId || 'session';
            actionTitle = titleOrTurnId;
            if (typeof details === 'object') {
                actionDetails = JSON.stringify(details);
            }
        }
        this.actionCounter++;
        const actionId = `a${String(this.actionCounter).padStart(4, '0')}`;

        const event: ActionEvent = {
            schema_version: JOURNAL_SCHEMA_VERSION,
            event_id: generateUUID(),
            event_type: 'action',
            timestamp: new Date().toISOString(),
            workspace: this.getWorkspaceInfo(),
            session_id: this.sessionId!,
            mode: this.getCurrentMode(),
            action_id: actionId,
            turn_id: turnId,
            title: actionTitle,
            status: 'open',
            details: actionDetails,
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
            mode: this.getCurrentMode(),
            checks
        };

        await this.appendEvent(event);
    }

    /**
     * Append an event to the journal file - throws on failure, no buffering
     */
    private async appendEvent(event: JournalEvent): Promise<void> {
        if (!this.sessionFilePath) {
            throw new Error('Journal session not initialized - call ensureSession() first');
        }

        const line = JSON.stringify(event) + '\n';
        await fs.promises.appendFile(this.sessionFilePath, line, 'utf8');
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
     * For V1, returns null if not initialized via MCP
     */
    private getCurrentMode(): { agent_mode: 'ck3lens' | 'ck3raven-dev' | null; safety: 'safe' } {
        // In V1, we don't read from MCP mode file
        // This could be extended to read ~/.ck3raven/mode.txt if needed
        return {
            agent_mode: null,
            safety: 'safe'
        };
    }

    /**
     * Check if journal is writable - throws on error, does not silently return false
     */
    async isWritable(): Promise<boolean> {
        const workspaceRoot = this.getWorkspaceRoot();
        if (!workspaceRoot) {
            throw new Error('No workspace root available for journal');
        }

        const testDir = path.join(workspaceRoot, '.ck3raven', 'chats');
        await fs.promises.mkdir(testDir, { recursive: true });

        const testFile = path.join(testDir, '.write_test');
        await fs.promises.writeFile(testFile, 'test', 'utf8');
        await fs.promises.unlink(testFile);

        return true;
    }

    /**
     * Get the journal file path (for diagnostics)
     */
    getSessionFilePath(): string | null {
        return this.sessionFilePath;
    }

    /**
     * Get current session ID (for actions.ts)
     */
    getCurrentSessionId(): string | null {
        return this.sessionId;
    }

    /**
     * Get current session file path (for actions.ts)
     */
    getCurrentSessionFile(): string | null {
        return this.sessionFilePath;
    }

    /**
     * Get the journal folder URI (for search.ts)
     */
    getJournalFolder(): vscode.Uri | undefined {
        const workspaceRoot = this.getWorkspaceRoot();
        if (!workspaceRoot) {
            return undefined;
        }
        return vscode.Uri.file(path.join(workspaceRoot, '.ck3raven', 'chats'));
    }

    dispose(): void {
        // No buffering, nothing to flush - journal is write-through
    }
}
