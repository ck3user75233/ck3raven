/**
 * Delta Detection
 * 
 * Compares current file state against baseline to find changes.
 * 
 * SAFETY: All chatSessions access is guarded by isShuttingDown flag.
 * During VS Code shutdown, these functions return empty results.
 * See: docs/bugs/JOURNAL_EXTRACTOR_CHAT_SESSION_LOSS.md
 */

import * as fs from 'fs';
import * as path from 'path';
import { BaselineSnapshot, DeltaResult, FileState } from './types';
import { getIsShuttingDown } from './windowManager';

/**
 * Detect changes in a directory since baseline was captured.
 * 
 * SAFETY: Returns empty delta during shutdown.
 * 
 * @param chatSessionsPath - Path to the chatSessions directory
 * @param baseline - Baseline snapshot from window start
 * @returns DeltaResult with added, modified, and deleted files
 */
export function detectDelta(
    chatSessionsPath: string,
    baseline: BaselineSnapshot
): DeltaResult {
    const result: DeltaResult = {
        added: [],
        modified: [],
        deleted: [],
    };

    // CRITICAL: Block chatSessions access during shutdown
    if (getIsShuttingDown()) {
        return result;
    }

    if (!fs.existsSync(chatSessionsPath)) {
        // If directory doesn't exist, all baseline files are "deleted"
        result.deleted = Array.from(baseline.keys());
        return result;
    }

    // Track which baseline files we've seen
    const seen = new Set<string>();

    try {
        const files = fs.readdirSync(chatSessionsPath);

        for (const file of files) {
            if (!file.endsWith('.json')) {
                continue;
            }

            // Re-check shutdown during iteration
            if (getIsShuttingDown()) {
                return result;
            }

            const filePath = path.join(chatSessionsPath, file);

            try {
                const stat = fs.statSync(filePath);
                if (!stat.isFile()) {
                    continue;
                }

                const currentState: FileState = {
                    mtime: stat.mtime.getTime(),
                    size: stat.size,
                };

                const baselineState = baseline.get(filePath);

                if (!baselineState) {
                    // New file
                    result.added.push(filePath);
                } else {
                    seen.add(filePath);
                    
                    // Check if modified (mtime or size changed)
                    if (
                        currentState.mtime > baselineState.mtime ||
                        currentState.size !== baselineState.size
                    ) {
                        result.modified.push(filePath);
                    }
                }
            } catch {
                // Skip files we can't stat
            }
        }
    } catch {
        // Can't read directory
    }

    // Find deleted files (in baseline but not seen)
    for (const filePath of baseline.keys()) {
        if (!seen.has(filePath) && !result.added.includes(filePath)) {
            // File was in baseline but not found in current scan
            if (!fs.existsSync(filePath)) {
                result.deleted.push(filePath);
            }
        }
    }

    return result;
}

/**
 * Get list of files that need to be processed (added + modified).
 */
export function getChangedFiles(delta: DeltaResult): string[] {
    return [...delta.added, ...delta.modified];
}

/**
 * Check if any changes were detected.
 */
export function hasChanges(delta: DeltaResult): boolean {
    return delta.added.length > 0 || 
           delta.modified.length > 0 || 
           delta.deleted.length > 0;
}
