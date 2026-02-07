/**
 * Baseline Snapshot
 * 
 * Captures the state of chatSessions files at window start
 * for delta detection on window close.
 * 
 * SAFETY: All chatSessions access is guarded by isShuttingDown flag.
 * During VS Code shutdown, these functions return empty results.
 * See: docs/bugs/JOURNAL_EXTRACTOR_CHAT_SESSION_LOSS.md
 */

import * as fs from 'fs';
import * as path from 'path';
import { BaselineSnapshot, FileState } from './types';
import { getIsShuttingDown } from './windowManager';

/**
 * Create a baseline snapshot of all files in a directory.
 * Records mtime and size for each file.
 * 
 * SAFETY: Returns empty map during shutdown.
 * 
 * @param chatSessionsPath - Path to the chatSessions directory
 * @returns Map of file path -> FileState
 */
export function createBaseline(chatSessionsPath: string): BaselineSnapshot {
    const baseline: BaselineSnapshot = new Map();

    // CRITICAL: Block chatSessions access during shutdown
    if (getIsShuttingDown()) {
        return baseline;
    }

    if (!fs.existsSync(chatSessionsPath)) {
        return baseline;
    }

    try {
        const files = fs.readdirSync(chatSessionsPath);
        
        for (const file of files) {
            if (!file.endsWith('.json')) {
                continue;
            }

            // Re-check shutdown during iteration
            if (getIsShuttingDown()) {
                return baseline;
            }

            const filePath = path.join(chatSessionsPath, file);
            
            try {
                const stat = fs.statSync(filePath);
                if (stat.isFile()) {
                    baseline.set(filePath, {
                        mtime: stat.mtime.getTime(),
                        size: stat.size,
                    });
                }
            } catch {
                // Skip files we can't stat
            }
        }
    } catch {
        // Can't read directory, return empty baseline
    }

    return baseline;
}

/**
 * Serialize a baseline snapshot to JSON for persistence.
 * (Used for debugging or if we need to persist baseline to disk)
 */
export function serializeBaseline(baseline: BaselineSnapshot): string {
    const obj: Record<string, FileState> = {};
    for (const [key, value] of baseline) {
        obj[key] = value;
    }
    return JSON.stringify(obj, null, 2);
}

/**
 * Deserialize a baseline snapshot from JSON.
 */
export function deserializeBaseline(json: string): BaselineSnapshot {
    const obj: Record<string, FileState> = JSON.parse(json);
    const baseline: BaselineSnapshot = new Map();
    for (const [key, value] of Object.entries(obj)) {
        baseline.set(key, value);
    }
    return baseline;
}
