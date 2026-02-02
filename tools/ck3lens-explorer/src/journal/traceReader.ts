/**
 * Trace Reader for FR-3 Journal Trace Capture
 * 
 * Reads per-window trace files written by the MCP server.
 * Trace files are JSONL format at ~/.ck3raven/traces/{window_id}.jsonl
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as readline from 'readline';

/** Trace event types */
export type TraceEventType = 'session_start' | 'tool_call';

/** Base trace event structure */
export interface TraceEvent {
    event: TraceEventType;
    timestamp: number;
    iso_time: string;
    window_id: string;
}

/** Session start event */
export interface SessionStartEvent extends TraceEvent {
    event: 'session_start';
}

/** Result summary from tool call */
export interface ResultSummary {
    reply_type: string;
    code: string;
    message: string;
    data_keys?: string[];
}

/** Tool call event */
export interface ToolCallEvent extends TraceEvent {
    event: 'tool_call';
    trace_id: string;
    tool: string;
    params: Record<string, unknown>;
    result_summary: ResultSummary | null;
    error: string | null;
    duration_ms: number;
}

/** Union type for all trace events */
export type AnyTraceEvent = SessionStartEvent | ToolCallEvent;

/**
 * Get the path to a window's trace file.
 */
export function getTraceFilePath(windowId: string): string {
    return path.join(os.homedir(), '.ck3raven', 'traces', `${windowId}.jsonl`);
}

/**
 * Check if a trace file exists for a window.
 */
export function traceFileExists(windowId: string): boolean {
    const tracePath = getTraceFilePath(windowId);
    return fs.existsSync(tracePath);
}

/**
 * Read all trace events from a window's trace file.
 * 
 * @param windowId The window ID
 * @returns Array of parsed trace events
 */
export async function readTraceEvents(windowId: string): Promise<AnyTraceEvent[]> {
    const tracePath = getTraceFilePath(windowId);
    
    if (!fs.existsSync(tracePath)) {
        return [];
    }
    
    const events: AnyTraceEvent[] = [];
    
    const fileStream = fs.createReadStream(tracePath, { encoding: 'utf-8' });
    const rl = readline.createInterface({
        input: fileStream,
        crlfDelay: Infinity,
    });
    
    for await (const line of rl) {
        if (!line.trim()) {
            continue;
        }
        try {
            const event = JSON.parse(line) as AnyTraceEvent;
            events.push(event);
        } catch (e) {
            // Skip malformed lines
            console.warn(`Failed to parse trace line: ${line.substring(0, 100)}`);
        }
    }
    
    return events;
}

/**
 * Read tool calls from a window's trace file, optionally filtered by time range.
 * 
 * @param windowId The window ID
 * @param afterTimestamp Only include events after this Unix timestamp (seconds)
 * @param beforeTimestamp Only include events before this Unix timestamp (seconds)
 * @returns Array of tool call events
 */
export async function readToolCalls(
    windowId: string,
    afterTimestamp?: number,
    beforeTimestamp?: number
): Promise<ToolCallEvent[]> {
    const events = await readTraceEvents(windowId);
    
    return events.filter((e): e is ToolCallEvent => {
        if (e.event !== 'tool_call') {
            return false;
        }
        if (afterTimestamp !== undefined && e.timestamp < afterTimestamp) {
            return false;
        }
        if (beforeTimestamp !== undefined && e.timestamp > beforeTimestamp) {
            return false;
        }
        return true;
    });
}

/**
 * Get a summary of tool usage from trace events.
 */
export function summarizeToolUsage(events: ToolCallEvent[]): Map<string, { count: number; totalMs: number; errors: number }> {
    const summary = new Map<string, { count: number; totalMs: number; errors: number }>();
    
    for (const event of events) {
        const existing = summary.get(event.tool) ?? { count: 0, totalMs: 0, errors: 0 };
        existing.count++;
        existing.totalMs += event.duration_ms;
        if (event.error) {
            existing.errors++;
        }
        summary.set(event.tool, existing);
    }
    
    return summary;
}

/**
 * Format trace events as markdown for journal archival.
 * 
 * @param events Tool call events to format
 * @returns Markdown string
 */
export function formatTraceAsMarkdown(events: ToolCallEvent[]): string {
    if (events.length === 0) {
        return '*(No MCP tool calls recorded)*\n';
    }
    
    const lines: string[] = [];
    lines.push('## MCP Tool Trace\n');
    lines.push(`**${events.length} tool calls captured**\n`);
    
    // Summary table
    const summary = summarizeToolUsage(events);
    lines.push('| Tool | Calls | Avg Time | Errors |');
    lines.push('|------|-------|----------|--------|');
    
    for (const [tool, stats] of summary.entries()) {
        const avgMs = (stats.totalMs / stats.count).toFixed(1);
        lines.push(`| \`${tool}\` | ${stats.count} | ${avgMs}ms | ${stats.errors} |`);
    }
    lines.push('');
    
    // Chronological list
    lines.push('### Chronological Trace\n');
    lines.push('```');
    
    for (const event of events) {
        const time = event.iso_time.substring(11, 19); // Extract HH:MM:SS
        const status = event.error ? '❌' : (event.result_summary?.reply_type === 'E' ? '⚠️' : '✓');
        const params = Object.keys(event.params).join(', ');
        
        lines.push(`[${time}] ${status} ${event.tool}(${params}) - ${event.duration_ms.toFixed(0)}ms`);
    }
    
    lines.push('```\n');
    
    return lines.join('\n');
}

/**
 * Clean up old trace files.
 * 
 * @param maxAgeDays Maximum age of trace files to keep
 * @returns Number of files deleted
 */
export function cleanupOldTraceFiles(maxAgeDays: number = 7): number {
    const tracesDir = path.join(os.homedir(), '.ck3raven', 'traces');
    
    if (!fs.existsSync(tracesDir)) {
        return 0;
    }
    
    const now = Date.now();
    const maxAgeMs = maxAgeDays * 24 * 60 * 60 * 1000;
    let deleted = 0;
    
    for (const file of fs.readdirSync(tracesDir)) {
        if (!file.endsWith('.jsonl')) {
            continue;
        }
        
        const filePath = path.join(tracesDir, file);
        const stats = fs.statSync(filePath);
        
        if (now - stats.mtimeMs > maxAgeMs) {
            fs.unlinkSync(filePath);
            deleted++;
        }
    }
    
    return deleted;
}
