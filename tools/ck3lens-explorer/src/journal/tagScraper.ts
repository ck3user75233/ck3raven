/**
 * Tag Scraper
 * 
 * Extracts tags from Copilot Chat messages using the pattern:
 *   *tag: tagname*
 * 
 * Tags are case-insensitive and normalized to lowercase.
 */

import { CopilotSession, CopilotMessage } from './backends/jsonBackend';

/** Regex pattern for tag extraction: *tag: name* */
const TAG_PATTERN = /\*tag:\s*([^*]+)\*/gi;

/**
 * Extract all tags from a message.
 * 
 * @param message - The message to scan
 * @returns Array of tag names (lowercased, trimmed)
 */
export function extractTagsFromMessage(message: CopilotMessage): string[] {
    const tags: string[] = [];
    
    let match;
    TAG_PATTERN.lastIndex = 0; // Reset regex state
    
    while ((match = TAG_PATTERN.exec(message.content)) !== null) {
        const tag = match[1].trim().toLowerCase();
        if (tag.length > 0 && !tags.includes(tag)) {
            tags.push(tag);
        }
    }
    
    return tags;
}

/**
 * Extract all tags from a session.
 * 
 * @param session - The session to scan
 * @returns Array of unique tag names (lowercased, sorted)
 */
export function extractTagsFromSession(session: CopilotSession): string[] {
    const tagSet = new Set<string>();
    
    for (const message of session.messages) {
        const tags = extractTagsFromMessage(message);
        for (const tag of tags) {
            tagSet.add(tag);
        }
    }
    
    return Array.from(tagSet).sort();
}

/**
 * Tag index entry for tags.jsonl.
 */
export interface TagIndexEntry {
    /** Tag name (lowercased) */
    tag: string;
    
    /** Window ID containing this tag */
    window_id: string;
    
    /** Session ID containing this tag */
    session_id: string;
    
    /** Timestamp when tag was indexed */
    indexed_at: string;
}

/**
 * Create index entries for a session's tags.
 * 
 * @param session - The session that was tagged
 * @param windowId - Current window ID
 * @returns Array of index entries
 */
export function createTagIndexEntries(
    session: CopilotSession,
    windowId: string
): TagIndexEntry[] {
    const tags = extractTagsFromSession(session);
    const now = new Date().toISOString();
    
    return tags.map(tag => ({
        tag,
        window_id: windowId,
        session_id: session.id,
        indexed_at: now,
    }));
}

/**
 * Format a tag for display (with the *tag: name* wrapper).
 */
export function formatTagForDisplay(tagName: string): string {
    return `*tag: ${tagName}*`;
}

/**
 * Check if a string contains any tags.
 */
export function containsTags(text: string): boolean {
    TAG_PATTERN.lastIndex = 0;
    return TAG_PATTERN.test(text);
}
