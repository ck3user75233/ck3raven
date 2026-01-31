/**
 * Structured Logger for CK3 Lens Extension
 * 
 * Provides fail-safe JSONL logging with:
 * - ISO 8601 UTC timestamps
 * - Instance ID for multi-window isolation
 * - Trace ID correlation for cross-component debugging
 * - Sensitive data redaction
 * - Buffered writes to reduce syscalls
 * - Graceful degradation on failure
 * 
 * See docs/CANONICAL_LOGS.md for full specification.
 * 
 * Usage:
 *   import { createStructuredLogger } from './structuredLogger';
 *   
 *   const logger = createStructuredLogger(instanceId, outputChannel);
 *   logger.info('ext.activate', 'Extension activating', { version: '1.0.0' });
 *   
 *   // With trace ID for cross-component correlation
 *   const traceId = logger.generateTraceId();
 *   logger.info('ext.lint', 'Lint requested', { file, traceId });
 *   
 *   // On deactivate
 *   logger.dispose();
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as vscode from 'vscode';

// Log file location per CANONICAL_LOGS.md
const LOG_DIR = path.join(os.homedir(), '.ck3raven', 'logs');
const LOG_FILE = path.join(LOG_DIR, 'ck3raven-ext.log');
const MAX_BUFFER_SIZE = 50;  // Flush after 50 entries
const FLUSH_INTERVAL_MS = 1000;  // Or every 1 second

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

interface LogEntry {
    ts: string;
    level: LogLevel;
    cat: string;
    inst: string;
    trace_id: string;
    msg: string;
    data?: Record<string, unknown>;
}

const LEVEL_ORDER: Record<LogLevel, number> = {
    DEBUG: 0,
    INFO: 1,
    WARN: 2,
    ERROR: 3
};

/**
 * Structured logger that writes to both file (JSONL) and VS Code output channel.
 */
export class StructuredLogger {
    private instanceId: string;
    private outputChannel: vscode.OutputChannel | null;
    private buffer: string[] = [];
    private flushTimer: NodeJS.Timeout | null = null;
    private logLevel: LogLevel = 'INFO';
    private currentTraceId: string = 'no-trace';
    private initialized: boolean = false;

    constructor(instanceId: string, outputChannel?: vscode.OutputChannel) {
        this.instanceId = instanceId;
        this.outputChannel = outputChannel || null;

        // Create log directory - throw if fails
        fs.mkdirSync(LOG_DIR, { recursive: true });
        this.initialized = true;

        // Start flush timer
        this.flushTimer = setInterval(() => this.flush(), FLUSH_INTERVAL_MS);
    }

    /**
     * Set the trace ID for correlating logs across components.
     */
    setTraceId(traceId: string): void {
        this.currentTraceId = traceId;
    }

    /**
     * Generate a new trace ID and set it as current.
     * Returns the generated ID for passing to MCP tools.
     */
    generateTraceId(): string {
        const id = Math.random().toString(36).substring(2, 10);
        this.currentTraceId = id;
        return id;
    }

    /**
     * Clear the current trace ID.
     */
    clearTraceId(): void {
        this.currentTraceId = 'no-trace';
    }

    /**
     * Set the minimum log level.
     */
    setLogLevel(level: LogLevel): void {
        this.logLevel = level;
    }

    private shouldLog(level: LogLevel): boolean {
        return LEVEL_ORDER[level] >= LEVEL_ORDER[this.logLevel];
    }

    private sanitize(data?: Record<string, unknown>): Record<string, unknown> | undefined {
        if (!data) return undefined;
        
        const sanitized: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(data)) {
            const keyLower = k.toLowerCase();
            // Mask API keys, tokens, secrets
            if (keyLower.includes('key') || 
                keyLower.includes('token') || 
                keyLower.includes('secret') ||
                keyLower.includes('password')) {
                sanitized[k] = '***REDACTED***';
            }
            // Truncate large strings
            else if (typeof v === 'string' && v.length > 1000) {
                sanitized[k] = v.substring(0, 1000) + '...[truncated]';
            }
            // Handle errors
            else if (v instanceof Error) {
                sanitized[k] = {
                    message: v.message,
                    name: v.name,
                    stack: v.stack?.substring(0, 1000)
                };
            }
            else {
                sanitized[k] = v;
            }
        }
        return sanitized;
    }

    private write(entry: LogEntry): void {
        const line = JSON.stringify(entry);

        // Add to buffer for file write
        this.buffer.push(line);

        // Mirror to output channel (human-readable format)
        if (this.outputChannel) {
            const dataStr = entry.data ? ` ${JSON.stringify(entry.data)}` : '';
            this.outputChannel.appendLine(`[${entry.level}] ${entry.cat}: ${entry.msg}${dataStr}`);
        }

        // Flush if buffer is full
        if (this.buffer.length >= MAX_BUFFER_SIZE) {
            this.flush();
        }
    }

    /**
     * Flush buffered log entries to disk - throws on failure
     */
    flush(): void {
        if (this.buffer.length === 0) return;

        const lines = this.buffer.join('\n') + '\n';
        this.buffer = [];

        // Write to file - throw on failure
        fs.appendFileSync(LOG_FILE, lines, 'utf-8');
    }

    /**
     * Core log function.
     */
    log(level: LogLevel, category: string, msg: string, data?: Record<string, unknown>): void {
        if (!this.shouldLog(level)) return;

        const entry: LogEntry = {
            ts: new Date().toISOString(),
            level,
            cat: category,
            inst: this.instanceId,
            trace_id: this.currentTraceId,
            msg,
        };
        
        if (data) {
            entry.data = this.sanitize(data);
        }

        this.write(entry);
    }

    /**
     * Log at DEBUG level.
     */
    debug(category: string, msg: string, data?: Record<string, unknown>): void {
        this.log('DEBUG', category, msg, data);
    }

    /**
     * Log at INFO level.
     */
    info(category: string, msg: string, data?: Record<string, unknown>): void {
        this.log('INFO', category, msg, data);
    }

    /**
     * Log at WARN level.
     */
    warn(category: string, msg: string, data?: Record<string, unknown>): void {
        this.log('WARN', category, msg, data);
    }

    /**
     * Log at ERROR level.
     */
    error(category: string, msg: string, data?: Record<string, unknown>): void {
        this.log('ERROR', category, msg, data);
    }

    /**
     * Bootstrap logging - before full initialization.
     * Always writes to console, bypasses file logging.
     */
    bootstrap(msg: string): void {
        const ts = new Date().toISOString();
        console.log(`[BOOTSTRAP ${ts}] ${msg}`);
    }

    /**
     * Show the output channel.
     */
    show(): void {
        this.outputChannel?.show();
    }

    /**
     * Dispose the logger - stop timer and flush remaining entries.
     * MUST be called in extension deactivate().
     */
    dispose(): void {
        // Log disposition before flushing
        this.info('ext.deactivate', 'Logger disposing', { instance_id: this.instanceId });

        // Stop the flush timer
        if (this.flushTimer) {
            clearInterval(this.flushTimer);
            this.flushTimer = null;
        }

        // Final flush
        this.flush();
    }
}

/**
 * Create a structured logger instance.
 * 
 * @param instanceId - Unique instance ID for multi-window isolation
 * @param outputChannel - VS Code output channel for human-readable logs
 */
export function createStructuredLogger(
    instanceId: string,
    outputChannel?: vscode.OutputChannel
): StructuredLogger {
    return new StructuredLogger(instanceId, outputChannel);
}

/**
 * Get the log file path (for debugging/testing).
 */
export function getLogFilePath(): string {
    return LOG_FILE;
}

/**
 * Get the log directory path (for debugging/testing).
 */
export function getLogDirPath(): string {
    return LOG_DIR;
}
