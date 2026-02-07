/**
 * Tag Index Management
 * 
 * Manages the tags.jsonl index for efficient tag searching across windows.
 */

import * as fs from 'fs';
import * as readline from 'readline';
import { TagIndexEntry } from './tagScraper';
import { getTagsIndexPath, getJournalBasePath } from './storage';
import { StructuredLogger } from '../utils/structuredLogger';

/**
 * Read all tag entries from a workspace's index.
 */
export function readTagIndex(workspaceKey: string): TagIndexEntry[] {
    const indexPath = getTagsIndexPath(workspaceKey);
    
    if (!fs.existsSync(indexPath)) {
        return [];
    }

    const entries: TagIndexEntry[] = [];
    const content = fs.readFileSync(indexPath, 'utf-8');
    
    for (const line of content.split('\n')) {
        if (line.trim()) {
            try {
                entries.push(JSON.parse(line));
            } catch {
                // Skip malformed lines
            }
        }
    }

    return entries;
}

/**
 * Search for tags matching a pattern across a workspace.
 * 
 * @param workspaceKey - Workspace to search
 * @param pattern - Tag name pattern (supports * wildcard)
 * @returns Matching entries
 */
export function searchTags(workspaceKey: string, pattern: string): TagIndexEntry[] {
    const entries = readTagIndex(workspaceKey);
    
    // Convert pattern to regex
    const regex = new RegExp(
        '^' + pattern.replace(/\*/g, '.*') + '$',
        'i'
    );
    
    return entries.filter(e => regex.test(e.tag));
}

/**
 * Get all unique tags in a workspace.
 */
export function getUniqueTags(workspaceKey: string): string[] {
    const entries = readTagIndex(workspaceKey);
    const tags = new Set(entries.map(e => e.tag));
    return Array.from(tags).sort();
}

/**
 * Get tag statistics for a workspace.
 */
export function getTagStats(workspaceKey: string): {
    total_entries: number;
    unique_tags: number;
    tags_by_count: Record<string, number>;
} {
    const entries = readTagIndex(workspaceKey);
    const counts: Record<string, number> = {};
    
    for (const entry of entries) {
        counts[entry.tag] = (counts[entry.tag] || 0) + 1;
    }

    return {
        total_entries: entries.length,
        unique_tags: Object.keys(counts).length,
        tags_by_count: counts,
    };
}

/**
 * Get entries for a specific session.
 */
export function getSessionTags(workspaceKey: string, sessionId: string): TagIndexEntry[] {
    const entries = readTagIndex(workspaceKey);
    return entries.filter(e => e.session_id === sessionId);
}

/**
 * Get entries from a specific window.
 */
export function getWindowTags(workspaceKey: string, windowId: string): TagIndexEntry[] {
    const entries = readTagIndex(workspaceKey);
    return entries.filter(e => e.window_id === windowId);
}

/**
 * Rebuild the tag index for a workspace from all window manifests.
 * Useful after corruption or for maintenance.
 */
export async function rebuildTagIndex(
    workspaceKey: string, 
    logger: StructuredLogger
): Promise<{ entries_written: number; windows_scanned: number }> {
    const basePath = getJournalBasePath();
    const workspacePath = `${basePath}/${workspaceKey}/windows`;
    const indexPath = getTagsIndexPath(workspaceKey);
    
    if (!fs.existsSync(workspacePath)) {
        return { entries_written: 0, windows_scanned: 0 };
    }

    const entries: TagIndexEntry[] = [];
    let windowsScanned = 0;

    // Scan all window directories
    const windowDirs = fs.readdirSync(workspacePath);
    
    for (const windowId of windowDirs) {
        const manifestPath = `${workspacePath}/${windowId}/manifest.json`;
        
        if (!fs.existsSync(manifestPath)) {
            continue;
        }

        windowsScanned++;

        try {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
            
            // For each export, read the session file and extract tags
            for (const exp of manifest.exports || []) {
                const sessionPath = `${workspacePath}/${windowId}/${exp.session_id}.json`;
                
                if (!fs.existsSync(sessionPath)) {
                    continue;
                }

                for (const tag of exp.tags || []) {
                    entries.push({
                        tag,
                        session_id: exp.session_id,
                        window_id: windowId,
                        indexed_at: new Date().toISOString(),
                    });
                }
            }
        } catch (err) {
            logger.warn('ext.journal.index', 'Failed to process manifest', {
                window_id: windowId,
                error: (err as Error).message,
            });
        }
    }

    // Write new index
    if (entries.length > 0) {
        const lines = entries.map(e => JSON.stringify(e)).join('\n') + '\n';
        fs.mkdirSync(`${basePath}/${workspaceKey}`, { recursive: true });
        fs.writeFileSync(indexPath, lines, 'utf-8');
    } else if (fs.existsSync(indexPath)) {
        fs.unlinkSync(indexPath);
    }

    logger.info('ext.journal.index', 'Tag index rebuilt', {
        workspace_key: workspaceKey,
        entries_written: entries.length,
        windows_scanned: windowsScanned,
    });

    return { entries_written: entries.length, windows_scanned: windowsScanned };
}

/**
 * List all workspace keys that have journal data.
 */
export function listWorkspaces(): string[] {
    const basePath = getJournalBasePath();
    const journalsPath = `${basePath}`;
    
    if (!fs.existsSync(journalsPath)) {
        return [];
    }

    const entries = fs.readdirSync(journalsPath, { withFileTypes: true });
    return entries
        .filter(e => e.isDirectory() && e.name.length === 64) // SHA-256 hex = 64 chars
        .map(e => e.name);
}

/**
 * Get window IDs for a workspace.
 */
export function listWindows(workspaceKey: string): string[] {
    const basePath = getJournalBasePath();
    const windowsPath = `${basePath}/${workspaceKey}/windows`;
    
    if (!fs.existsSync(windowsPath)) {
        return [];
    }

    const entries = fs.readdirSync(windowsPath, { withFileTypes: true });
    return entries
        .filter(e => e.isDirectory())
        .map(e => e.name)
        .sort(); // ISO timestamps sort correctly
}
