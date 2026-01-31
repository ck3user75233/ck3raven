/**
 * Chat Journal Type Definitions
 *
 * TypeScript interfaces for JSONL journal events.
 * V1 Brief compliance: append-only, workspace-local journaling.
 */

/**
 * Schema version for journal events.
 * Increment when making breaking changes to event structure.
 */
export const JOURNAL_SCHEMA_VERSION = 1;

/**
 * Size limit for individual fields before truncation (5MB)
 * Q6 decision: enforce limits via truncation, never reject
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
 * Fields: byte_len, sha256, preview
 */
export interface TruncationInfo {
    truncated: true;
    byte_len: number;
    sha256: string;
    preview: string;
}

/**
 * Type guard to check if a value is TruncationInfo
 */
export function isTruncationInfo(value: unknown): value is TruncationInfo {
    return (
        typeof value === 'object' &&
        value !== null &&
        'truncated' in value &&
        (value as TruncationInfo).truncated === true
    );
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
        mcp_tools_registered: boolean;
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
