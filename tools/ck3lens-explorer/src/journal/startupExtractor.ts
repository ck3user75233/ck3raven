/**
 * Startup Snapshot Extractor
 * 
 * Safely extracts chat sessions at startup using copy-then-read strategy.
 * 
 * CRITICAL INVARIANT: Never reads directly from VS Code's chatSessions while VS Code is running.
 * All reads are from snapshot copies in our extension storage.
 * 
 * Flow:
 * 1. On extension activation (after delay), check for pending extraction markers
 * 2. Copy chatSessions files to snapshot directory (open → read → close per file)
 * 3. Parse only from snapshots
 * 4. Append to journal (NDJSON rolling append)
 * 
 * See: docs/bugs/JOURNAL_EXTRACTOR_CHAT_SESSION_LOSS.md
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { StructuredLogger } from '../utils/structuredLogger';
import { LOG_CATEGORIES } from './types';
import { 
    getWorkspaceJournalPath, 
    getChatArchivesPath,
    initializeStorage,
    enforceJournalsBoundary,
} from './storage';
import { deriveActiveWorkspaceKey } from './workspaceKey';
import { 
    PendingExtractionMarker, 
    getPendingMarkerPath,
    getIsShuttingDown,
} from './windowManager';
import { parseSessionFile } from './backends/jsonBackend';
import { fingerprintSession } from './fingerprint';
import { sessionToMarkdown } from './markdownExport';

/** Delay before running startup extraction (ms) - avoid competing with VS Code startup */
const STARTUP_DELAY_MS = 3000;

/** Maximum files to process per batch (yield between batches for responsiveness) */
const BATCH_SIZE = 5;

/** State file tracking what's been processed */
interface ExtractorState {
    last_snapshot_ts: string;
    processed_files: Record<string, {
        mtime: number;
        size: number;
        extracted_at: string;
    }>;
}

/**
 * Get path to extractor state file for a workspace.
 */
function getStatePath(workspaceKey: string): string {
    return path.join(getWorkspaceJournalPath(workspaceKey), 'extractor_state.json');
}

/**
 * Get path to snapshots directory for a workspace.
 */
function getSnapshotsPath(workspaceKey: string): string {
    return path.join(getWorkspaceJournalPath(workspaceKey), 'snapshots');
}

/**
 * Load extractor state (or create default).
 */
function loadState(workspaceKey: string): ExtractorState {
    const statePath = getStatePath(workspaceKey);
    try {
        if (fs.existsSync(statePath)) {
            return JSON.parse(fs.readFileSync(statePath, 'utf-8'));
        }
    } catch {
        // Corrupted state - start fresh
    }
    return {
        last_snapshot_ts: '',
        processed_files: {},
    };
}

/**
 * Save extractor state.
 */
function saveState(workspaceKey: string, state: ExtractorState, logger: StructuredLogger): void {
    const statePath = getStatePath(workspaceKey);
    try {
        fs.mkdirSync(path.dirname(statePath), { recursive: true });
        fs.writeFileSync(statePath, JSON.stringify(state, null, 2), 'utf-8');
    } catch (err) {
        logger.warn(LOG_CATEGORIES.EXTRACTION, 'Failed to save extractor state', {
            error: (err as Error).message,
        });
    }
}

/**
 * Copy chat session files to snapshot directory.
 * Uses open → read → close per file to minimize lock duration.
 * 
 * @returns Array of files successfully copied
 */
function copyToSnapshot(
    livePath: string,
    snapshotPath: string,
    logger: StructuredLogger
): string[] {
    const copied: string[] = [];
    
    // GUARD: Never copy during shutdown
    if (getIsShuttingDown()) {
        logger.warn(LOG_CATEGORIES.EXTRACTION, 'Aborting snapshot copy - shutting down', {});
        return copied;
    }
    
    // Ensure snapshot directory exists
    fs.mkdirSync(snapshotPath, { recursive: true });
    
    let files: string[];
    try {
        files = fs.readdirSync(livePath).filter(f => f.endsWith('.json'));
    } catch (err) {
        logger.warn(LOG_CATEGORIES.EXTRACTION, 'Cannot read live chatSessions', {
            path: livePath,
            error: (err as Error).message,
        });
        return copied;
    }
    
    for (const file of files) {
        // GUARD: Check shutdown between files
        if (getIsShuttingDown()) {
            logger.info(LOG_CATEGORIES.EXTRACTION, 'Snapshot copy interrupted by shutdown', {
                copied_so_far: copied.length,
            });
            break;
        }
        
        const srcPath = path.join(livePath, file);
        const dstPath = path.join(snapshotPath, file);
        
        try {
            // Open → Read → Close (minimal lock duration)
            const content = fs.readFileSync(srcPath, 'utf-8');
            fs.writeFileSync(dstPath, content, 'utf-8');
            copied.push(file);
        } catch (err) {
            // File locked or inaccessible - skip and continue
            logger.debug(LOG_CATEGORIES.EXTRACTION, 'Skipped locked file', {
                file,
                error: (err as Error).message,
            });
        }
    }
    
    logger.info(LOG_CATEGORIES.EXTRACTION, 'Snapshot copy complete', {
        live_path: livePath,
        snapshot_path: snapshotPath,
        files_copied: copied.length,
        files_total: files.length,
    });
    
    return copied;
}

/**
 * Extract sessions from snapshot directory.
 * Only processes files that are new or changed since last extraction.
 */
async function extractFromSnapshot(
    workspaceKey: string,
    snapshotPath: string,
    state: ExtractorState,
    logger: StructuredLogger
): Promise<{ extracted: number; errors: number }> {
    const result = { extracted: 0, errors: 0 };
    
    if (!fs.existsSync(snapshotPath)) {
        return result;
    }
    
    const files = fs.readdirSync(snapshotPath).filter(f => f.endsWith('.json'));
    const outputDir = getChatArchivesPath(workspaceKey);
    fs.mkdirSync(outputDir, { recursive: true });
    
    let batch = 0;
    for (const file of files) {
        // GUARD: Check shutdown
        if (getIsShuttingDown()) {
            logger.info(LOG_CATEGORIES.EXTRACTION, 'Extraction interrupted by shutdown', {
                extracted: result.extracted,
            });
            break;
        }
        
        const filePath = path.join(snapshotPath, file);
        
        try {
            const stat = fs.statSync(filePath);
            const fileKey = file;
            
            // Check if already processed with same mtime/size
            const prev = state.processed_files[fileKey];
            if (prev && prev.mtime === stat.mtime.getTime() && prev.size === stat.size) {
                continue; // Already processed
            }
            
            // Parse session
            const session = parseSessionFile(filePath);
            if (!session || session.errors?.length || session.messages.length === 0) {
                continue; // Invalid or empty
            }
            
            // Compute fingerprint
            const fingerprint = fingerprintSession(session);
            
            // Write session JSON
            const jsonPath = path.join(outputDir, `${session.id}.json`);
            enforceJournalsBoundary(jsonPath, logger);
            fs.writeFileSync(jsonPath, JSON.stringify(session.raw, null, 2), 'utf-8');
            
            // Write Markdown export
            const mdPath = path.join(outputDir, `${session.id}.md`);
            enforceJournalsBoundary(mdPath, logger);
            const markdown = sessionToMarkdown(session);
            fs.writeFileSync(mdPath, markdown, 'utf-8');
            
            // Update state
            state.processed_files[fileKey] = {
                mtime: stat.mtime.getTime(),
                size: stat.size,
                extracted_at: new Date().toISOString(),
            };
            
            result.extracted++;
            batch++;
            
            // Yield between batches for UI responsiveness
            if (batch >= BATCH_SIZE) {
                batch = 0;
                await new Promise(resolve => setImmediate(resolve));
            }
            
        } catch (err) {
            logger.warn(LOG_CATEGORIES.EXTRACTION, 'Failed to extract session', {
                file,
                error: (err as Error).message,
            });
            result.errors++;
        }
    }
    
    return result;
}

/**
 * Process pending extraction marker from previous shutdown.
 */
function processPendingMarker(
    workspaceKey: string,
    logger: StructuredLogger
): PendingExtractionMarker | null {
    const markerPath = getPendingMarkerPath(workspaceKey);
    
    if (!fs.existsSync(markerPath)) {
        return null;
    }
    
    try {
        const marker: PendingExtractionMarker = JSON.parse(
            fs.readFileSync(markerPath, 'utf-8')
        );
        
        logger.info(LOG_CATEGORIES.EXTRACTION, 'Found pending extraction marker', {
            window_id: marker.window_id,
            shutdown_at: marker.shutdown_at,
        });
        
        // Delete marker after reading
        fs.unlinkSync(markerPath);
        
        return marker;
    } catch (err) {
        logger.warn(LOG_CATEGORIES.EXTRACTION, 'Failed to read pending marker', {
            error: (err as Error).message,
        });
        return null;
    }
}

/**
 * Run startup extraction.
 * 
 * Called during extension activation after a delay.
 * Uses copy-then-read to safely extract without blocking VS Code.
 */
export async function runStartupExtraction(
    context: vscode.ExtensionContext,
    logger: StructuredLogger
): Promise<void> {
    // GUARD: Never run during shutdown
    if (getIsShuttingDown()) {
        logger.info(LOG_CATEGORIES.EXTRACTION, 'Skipping startup extraction - shutting down', {});
        return;
    }
    
    const workspaceKey = deriveActiveWorkspaceKey();
    if (!workspaceKey) {
        logger.debug(LOG_CATEGORIES.EXTRACTION, 'No workspace - skipping startup extraction', {});
        return;
    }
    
    logger.info(LOG_CATEGORIES.EXTRACTION, 'Starting startup extraction', {
        workspace_key: workspaceKey,
    });
    
    try {
        // Initialize storage
        initializeStorage(workspaceKey, logger);
        
        // Check for pending marker from previous shutdown
        const pending = processPendingMarker(workspaceKey, logger);
        if (pending) {
            logger.info(LOG_CATEGORIES.EXTRACTION, 'Processing pending extraction', {
                window_id: pending.window_id,
                from_shutdown: pending.shutdown_at,
            });
        }
        
        // Derive live chatSessions path from context
        if (!context.storageUri) {
            logger.debug(LOG_CATEGORIES.EXTRACTION, 'No storageUri - skipping extraction', {});
            return;
        }
        
        const extensionStoragePath = context.storageUri.fsPath;
        const workspaceStorageRoot = path.dirname(extensionStoragePath);
        const liveChatSessionsPath = path.join(workspaceStorageRoot, 'chatSessions');
        
        if (!fs.existsSync(liveChatSessionsPath)) {
            logger.debug(LOG_CATEGORIES.EXTRACTION, 'No chatSessions directory', {
                path: liveChatSessionsPath,
            });
            return;
        }
        
        // Load state
        const state = loadState(workspaceKey);
        
        // Create timestamped snapshot directory
        const snapshotTs = new Date().toISOString().replace(/[:.]/g, '-');
        const snapshotPath = path.join(getSnapshotsPath(workspaceKey), snapshotTs);
        
        // Copy to snapshot (safe copy-then-read)
        const copied = copyToSnapshot(liveChatSessionsPath, snapshotPath, logger);
        
        if (copied.length === 0) {
            logger.info(LOG_CATEGORIES.EXTRACTION, 'No files to extract', {});
            return;
        }
        
        // Extract from snapshot
        const result = await extractFromSnapshot(workspaceKey, snapshotPath, state, logger);
        
        // Update state
        state.last_snapshot_ts = snapshotTs;
        saveState(workspaceKey, state, logger);
        
        logger.info(LOG_CATEGORIES.EXTRACTION, 'Startup extraction complete', {
            workspace_key: workspaceKey,
            files_copied: copied.length,
            sessions_extracted: result.extracted,
            errors: result.errors,
        });
        
    } catch (err) {
        // Non-fatal - log and continue
        logger.error(LOG_CATEGORIES.EXTRACTION, 'Startup extraction failed', {
            error: (err as Error).message,
            stack: (err as Error).stack,
        });
    }
}

/**
 * Schedule startup extraction with delay.
 * 
 * Called from extension activation. Uses setTimeout to avoid
 * competing with VS Code's own startup persistence.
 */
export function scheduleStartupExtraction(
    context: vscode.ExtensionContext,
    logger: StructuredLogger
): void {
    logger.info(LOG_CATEGORIES.EXTRACTION, 'Scheduling startup extraction', {
        delay_ms: STARTUP_DELAY_MS,
    });
    
    setTimeout(async () => {
        // GUARD: Check shutdown before running
        if (getIsShuttingDown()) {
            logger.info(LOG_CATEGORIES.EXTRACTION, 'Startup extraction cancelled - shutting down', {});
            return;
        }
        
        await runStartupExtraction(context, logger);
    }, STARTUP_DELAY_MS);
}
