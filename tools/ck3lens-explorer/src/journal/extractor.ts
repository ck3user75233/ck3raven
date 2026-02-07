/**
 * Session Extractor
 * 
 * Main extraction logic for journal windows.
 * Ties together parsing, fingerprinting, tag scraping, and export.
 * 
 * SAFETY: Extraction is guarded by isShuttingDown flag.
 * During VS Code shutdown, do NOT call extractWindow().
 * See: docs/bugs/JOURNAL_EXTRACTOR_CHAT_SESSION_LOSS.md
 */

import * as fs from 'fs';
import * as path from 'path';
import { 
    WindowState, 
    ExtractionResult, 
    ManifestExport, 
    ManifestError,
    ManifestTelemetry,
    CloseReason,
    LOG_CATEGORIES,
} from './types';
import { StructuredLogger } from '../utils/structuredLogger';
import { detectDelta, getChangedFiles } from './delta';
import { parseSessionFile, CopilotSession } from './backends/jsonBackend';
import { fingerprintSession } from './fingerprint';
import { extractTagsFromSession, createTagIndexEntries, TagIndexEntry } from './tagScraper';
import { sessionToMarkdown } from './markdownExport';
import { 
    createManifest, 
    createEmptyTelemetry, 
    createManifestExport, 
    createManifestError,
    writeManifest,
} from './manifest';
import { getTagsIndexPath, enforceJournalsBoundary } from './storage';
import { 
    readToolCalls, 
    formatTraceAsMarkdown, 
    traceFileExists,
    ToolCallEvent,
} from './traceReader';
import { getIsShuttingDown } from './windowManager';

/**
 * Run extraction for a journal window.
 * 
 * SAFETY: Returns empty result if extension is shutting down.
 * 
 * @param window - The active window state
 * @param closeReason - Reason for closing
 * @param logger - Structured logger
 * @returns Extraction result
 */
export async function extractWindow(
    window: WindowState,
    closeReason: CloseReason,
    logger: StructuredLogger
): Promise<ExtractionResult> {
    // CRITICAL: Block extraction during shutdown
    // This prevents file locking issues with VS Code's workspaceStorage
    if (getIsShuttingDown()) {
        logger.warn(LOG_CATEGORIES.EXTRACTION, 'Extraction blocked during shutdown', {
            window_id: window.window_id,
            close_reason: closeReason,
        });
        return {
            success: false,
            exports: [],
            telemetry: createEmptyTelemetry(),
            errors: [{
                code: 'JRN-EXT-E-003',
                message: 'Extraction blocked: extension is shutting down',
            }],
        };
    }

    const startTime = Date.now();
    const telemetry: ManifestTelemetry = createEmptyTelemetry();
    const exports: ManifestExport[] = [];
    const errors: ManifestError[] = [];
    const tagEntries: TagIndexEntry[] = [];

    logger.info(LOG_CATEGORIES.EXTRACTION, 'Starting extraction', {
        window_id: window.window_id,
        workspace_key: window.workspace_key,
        close_reason: closeReason,
        baseline_files: window.baseline.size,
        chat_sessions_path: window.chatSessionsPath,
    });

    try {
        // Detect changes since baseline
        const delta = detectDelta(window.chatSessionsPath, window.baseline);
        const changedFiles = getChangedFiles(delta);
        
        telemetry.sessions_scanned = window.baseline.size;
        telemetry.sessions_changed = changedFiles.length;

        logger.info(LOG_CATEGORIES.DELTA, 'Delta detected', {
            window_id: window.window_id,
            added: delta.added.length,
            modified: delta.modified.length,
            deleted: delta.deleted.length,
            added_files: delta.added,
            modified_files: delta.modified,
        });

        // Process each changed file
        for (const filePath of changedFiles) {
            try {
                const result = processSession(filePath, window, logger);
                if (result) {
                    exports.push(result.export);
                    tagEntries.push(...result.tagEntries);
                    telemetry.sessions_exported++;
                }
            } catch (err) {
                logger.error(LOG_CATEGORIES.EXTRACTION, 'Failed to process session', {
                    file: filePath,
                    error: (err as Error).message,
                });
                errors.push(createManifestError(
                    'JRN-EXT-E-002',
                    err as Error,
                    path.basename(filePath, '.json')
                ));
            }
        }

        // Write tag index entries
        if (tagEntries.length > 0) {
            appendTagIndex(window.workspace_key, tagEntries, logger);
        }

        // FR-3: Capture MCP tool trace for this window
        const traceExport = await captureWindowTrace(window, logger);
        if (traceExport) {
            telemetry.tool_calls_captured = traceExport.toolCallCount;
        }

    } catch (err) {
        logger.error(LOG_CATEGORIES.EXTRACTION, 'Extraction failed', {
            window_id: window.window_id,
            error: (err as Error).message,
            stack: (err as Error).stack,
        });
        errors.push(createManifestError('JRN-EXT-E-001', err as Error));
    }

    // Calculate duration
    telemetry.extraction_duration_ms = Date.now() - startTime;

    // Create and write manifest (ALWAYS - JRN-VIS-001)
    const manifest = createManifest(
        window.window_id,
        window.workspace_key,
        window.started_at,
        new Date().toISOString(),
        closeReason,
        exports,
        telemetry,
        errors
    );

    writeManifest(manifest, window.outputPath, logger);

    logger.info(LOG_CATEGORIES.EXTRACTION, 'Extraction complete', {
        window_id: window.window_id,
        sessions_exported: telemetry.sessions_exported,
        errors: errors.length,
        duration_ms: telemetry.extraction_duration_ms,
        output_path: window.outputPath,
    });

    return {
        success: errors.length === 0,
        exports,
        telemetry,
        errors,
    };
}

/**
 * Process a single session file.
 */
function processSession(
    filePath: string,
    window: WindowState,
    logger: StructuredLogger
): { export: ManifestExport; tagEntries: TagIndexEntry[] } | null {
    logger.debug(LOG_CATEGORIES.EXTRACTION, 'Processing session file', {
        file: filePath,
        window_id: window.window_id,
    });

    // Parse session
    const session = parseSessionFile(filePath);
    if (!session || session.errors?.length) {
        logger.warn(LOG_CATEGORIES.EXTRACTION, 'Failed to parse session', {
            file: filePath,
            errors: session?.errors,
        });
        return null;
    }

    if (session.messages.length === 0) {
        logger.debug(LOG_CATEGORIES.EXTRACTION, 'Skipping empty session', {
            session_id: session.id,
        });
        return null;
    }

    // Compute fingerprint
    const fingerprint = fingerprintSession(session);

    // Extract tags
    const tags = extractTagsFromSession(session);
    const tagEntries = createTagIndexEntries(session, window.window_id);

    // Write session JSON
    const jsonPath = path.join(window.outputPath, `${session.id}.json`);
    enforceJournalsBoundary(jsonPath, logger);
    fs.writeFileSync(jsonPath, JSON.stringify(session.raw, null, 2), 'utf-8');

    // Write Markdown export
    const mdPath = path.join(window.outputPath, `${session.id}.md`);
    enforceJournalsBoundary(mdPath, logger);
    const markdown = sessionToMarkdown(session);
    fs.writeFileSync(mdPath, markdown, 'utf-8');

    logger.info(LOG_CATEGORIES.EXTRACTION, 'Session exported', {
        session_id: session.id,
        messages: session.messages.length,
        tags: tags.length,
        fingerprint: fingerprint.substring(0, 16) + '...',
        json_path: jsonPath,
        md_path: mdPath,
    });

    return {
        export: createManifestExport(session.id, fingerprint, tags),
        tagEntries,
    };
}

/**
 * Append tag entries to the workspace's tag index.
 */
function appendTagIndex(
    workspaceKey: string,
    entries: TagIndexEntry[],
    logger: StructuredLogger
): void {
    const indexPath = getTagsIndexPath(workspaceKey);
    
    try {
        enforceJournalsBoundary(indexPath, logger);
        
        // Ensure directory exists
        fs.mkdirSync(path.dirname(indexPath), { recursive: true });
        
        // Append entries as JSONL
        const lines = entries.map(e => JSON.stringify(e)).join('\n') + '\n';
        fs.appendFileSync(indexPath, lines, 'utf-8');
        
        logger.debug(LOG_CATEGORIES.TAG_INDEX, 'Tags indexed', {
            workspace_key: workspaceKey,
            entries: entries.length,
            index_path: indexPath,
        });
    } catch (err) {
        logger.error(LOG_CATEGORIES.TAG_INDEX, 'Failed to append tag index', {
            workspace_key: workspaceKey,
            error: (err as Error).message,
        });
    }
}

/**
 * FR-3: Capture MCP tool trace for this window session.
 * 
 * Reads tool calls from the per-window trace file and exports them
 * as a markdown file alongside the session exports.
 */
async function captureWindowTrace(
    window: WindowState,
    logger: StructuredLogger
): Promise<{ toolCallCount: number } | null> {
    // Check if trace file exists for this window
    if (!traceFileExists(window.window_id)) {
        logger.debug(LOG_CATEGORIES.EXTRACTION, 'No trace file for window', {
            window_id: window.window_id,
        });
        return null;
    }

    try {
        // Read tool calls from trace file
        // Filter to calls during this window session
        const startTs = new Date(window.started_at).getTime() / 1000;
        const toolCalls = await readToolCalls(window.window_id, startTs);

        if (toolCalls.length === 0) {
            logger.debug(LOG_CATEGORIES.EXTRACTION, 'No tool calls in trace', {
                window_id: window.window_id,
            });
            return null;
        }

        // Write trace markdown file
        const tracePath = path.join(window.outputPath, '_tool_trace.md');
        enforceJournalsBoundary(tracePath, logger);
        
        const markdown = formatTraceAsMarkdown(toolCalls);
        fs.writeFileSync(tracePath, markdown, 'utf-8');

        logger.info(LOG_CATEGORIES.EXTRACTION, 'Tool trace captured', {
            window_id: window.window_id,
            tool_calls: toolCalls.length,
            trace_path: tracePath,
        });

        return { toolCallCount: toolCalls.length };

    } catch (err) {
        logger.error(LOG_CATEGORIES.EXTRACTION, 'Failed to capture tool trace', {
            window_id: window.window_id,
            error: (err as Error).message,
        });
        return null;
    }
}
