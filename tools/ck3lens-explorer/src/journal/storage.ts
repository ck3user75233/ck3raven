/**
 * Journal Storage Management
 * 
 * Manages the journal storage directory structure at ~/.ck3raven/journals/
 * 
 * Directory structure:
 *   ~/.ck3raven/journals/{workspace_key}/
 *   ├── windows/
 *   │   └── {window_id}/
 *   │       ├── manifest.json
 *   │       ├── {session_id}.json
 *   │       └── {session_id}.md
 *   └── index/
 *       └── tags.jsonl
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { JournalConfig, LOG_CATEGORIES } from './types';
import { StructuredLogger } from '../utils/structuredLogger';

/** Base path for all journals */
const JOURNALS_BASE = path.join(os.homedir(), '.ck3raven', 'journals');

/**
 * Get the base journals directory path.
 */
export function getJournalsBasePath(): string {
    return JOURNALS_BASE;
}

/**
 * Alias for getJournalsBasePath for consistency.
 */
export function getJournalBasePath(): string {
    return JOURNALS_BASE;
}

/**
 * Get the storage directory for a specific workspace.
 * 
 * @param workspaceKey - SHA-256 derived workspace key
 * @returns Path to workspace's journal directory
 */
export function getWorkspaceJournalPath(workspaceKey: string): string {
    return path.join(JOURNALS_BASE, workspaceKey);
}

/**
 * Get the windows directory for a workspace.
 */
export function getWindowsPath(workspaceKey: string): string {
    return path.join(getWorkspaceJournalPath(workspaceKey), 'windows');
}

/**
 * Get the index directory for a workspace.
 */
export function getIndexPath(workspaceKey: string): string {
    return path.join(getWorkspaceJournalPath(workspaceKey), 'index');
}

/**
 * Get the path for a specific window.
 * 
 * @param workspaceKey - Workspace identifier
 * @param windowId - Window identifier (ISO timestamp + counter)
 */
export function getWindowPath(workspaceKey: string, windowId: string): string {
    return path.join(getWindowsPath(workspaceKey), windowId);
}

/**
 * Get the manifest.json path for a window.
 */
export function getManifestPath(workspaceKey: string, windowId: string): string {
    return path.join(getWindowPath(workspaceKey, windowId), 'manifest.json');
}

/**
 * Get the tags.jsonl path for a workspace.
 */
export function getTagsIndexPath(workspaceKey: string): string {
    return path.join(getIndexPath(workspaceKey), 'tags.jsonl');
}

/**
 * Initialize storage for a workspace if it doesn't exist.
 * Creates the directory structure.
 * 
 * @param workspaceKey - Workspace identifier
 * @param logger - Structured logger
 * @returns true if successful, throws on failure
 */
export function initializeStorage(workspaceKey: string, logger: StructuredLogger): boolean {
    const workspacePath = getWorkspaceJournalPath(workspaceKey);
    const windowsPath = getWindowsPath(workspaceKey);
    const indexPath = getIndexPath(workspaceKey);

    // Create directories
    fs.mkdirSync(workspacePath, { recursive: true });
    fs.mkdirSync(windowsPath, { recursive: true });
    fs.mkdirSync(indexPath, { recursive: true });

    logger.debug('ext.journal.storage', 'Storage initialized', {
        workspace_key: workspaceKey,
        path: workspacePath,
    });

    return true;
}

/**
 * Initialize a window directory for storing exports.
 * 
 * @param workspaceKey - Workspace identifier
 * @param windowId - Window identifier
 * @returns Path to the window directory
 */
export function initializeWindow(workspaceKey: string, windowId: string): string {
    const windowPath = getWindowPath(workspaceKey, windowId);
    fs.mkdirSync(windowPath, { recursive: true });
    return windowPath;
}

/**
 * Check if a path is within the journals directory.
 * Used for boundary enforcement (CCE-VIS-001).
 * 
 * @param targetPath - Path to check
 * @returns true if path is within journals/
 */
export function isWithinJournals(targetPath: string): boolean {
    const normalizedTarget = path.resolve(targetPath);
    const normalizedBase = path.resolve(JOURNALS_BASE);
    return normalizedTarget.startsWith(normalizedBase);
}

/**
 * Enforce that a write is within journals directory.
 * Logs access_denied and throws if not.
 * 
 * @param targetPath - Path to validate
 * @param logger - Structured logger
 * @throws Error if path is outside journals/
 */
export function enforceJournalsBoundary(targetPath: string, logger: StructuredLogger): void {
    if (!isWithinJournals(targetPath)) {
        logger.warn(LOG_CATEGORIES.ACCESS_DENIED, 'Write attempted outside journals directory', {
            path: targetPath,
            rule: 'CCE-VIS-001',
        });
        throw new Error(`Access denied: path '${targetPath}' is outside journals directory`);
    }
}

/**
 * Generate a window ID from a timestamp.
 * Format: YYYY-MM-DDTHH-MM-SSZ_window-NNNN
 * 
 * @param date - Date for the window (defaults to now)
 * @param counter - Optional counter for uniqueness
 */
export function generateWindowId(date: Date = new Date(), counter?: number): string {
    const isoBase = date.toISOString()
        .replace(/:/g, '-')
        .replace(/\.\d{3}Z$/, 'Z');
    
    const counterStr = counter !== undefined 
        ? String(counter).padStart(4, '0')
        : String(Math.floor(Math.random() * 10000)).padStart(4, '0');
    
    return `${isoBase}_window-${counterStr}`;
}

/**
 * List all windows for a workspace.
 * 
 * @param workspaceKey - Workspace identifier
 * @returns Array of window IDs, sorted newest first
 */
export function listWindows(workspaceKey: string): string[] {
    const windowsPath = getWindowsPath(workspaceKey);
    
    if (!fs.existsSync(windowsPath)) {
        return [];
    }

    try {
        const entries = fs.readdirSync(windowsPath, { withFileTypes: true });
        const windows = entries
            .filter(e => e.isDirectory())
            .map(e => e.name)
            .sort()
            .reverse(); // Newest first (ISO dates sort chronologically)
        
        return windows;
    } catch {
        return [];
    }
}

/**
 * Get the default journal configuration.
 */
export function getDefaultConfig(): JournalConfig {
    return {
        journalsPath: JOURNALS_BASE,
        timeBucketSeconds: 60,
    };
}
