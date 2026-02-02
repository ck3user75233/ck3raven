/**
 * JSON Backend
 * 
 * Parses Copilot Chat session JSON files.
 * This is the primary backend for Phase 1 (SQLite backend is Phase 2+).
 */

import * as fs from 'fs';
import * as path from 'path';
import { SessionMetadata } from './types';

/**
 * Structure of a Copilot Chat message in the session JSON.
 */
export interface CopilotMessage {
    /** Role of the message author */
    role: 'user' | 'assistant' | 'system';
    
    /** Message content */
    content: string;
    
    /** Timestamp (if available) */
    timestamp?: number;
    
    /** Attachments (if available) */
    attachments?: CopilotAttachment[];
}

/**
 * Structure of an attachment in a Copilot Chat message.
 */
export interface CopilotAttachment {
    /** URI or path to the attachment */
    uri?: string;
    
    /** Type of attachment */
    type?: string;
    
    /** Additional data */
    [key: string]: unknown;
}

/**
 * Parsed Copilot Chat session.
 */
export interface CopilotSession {
    /** Session identifier */
    id: string;
    
    /** File path to the session JSON */
    filePath: string;
    
    /** Messages in the session */
    messages: CopilotMessage[];
    
    /** Raw JSON content (for export) */
    raw: unknown;
    
    /** Parse errors (if any) */
    errors?: string[];
}

/**
 * Read and parse a session JSON file.
 * 
 * @param filePath - Path to the session JSON file
 * @returns Parsed session or null on error
 */
export function parseSessionFile(filePath: string): CopilotSession | null {
    try {
        const content = fs.readFileSync(filePath, 'utf-8');
        const raw = JSON.parse(content);
        
        // Extract session ID from filename
        const id = path.basename(filePath, '.json');
        
        // Parse messages from the session structure
        // Copilot Chat JSON structure may vary; handle common patterns
        const messages = extractMessages(raw);
        
        return {
            id,
            filePath,
            messages,
            raw,
        };
    } catch (err) {
        return {
            id: path.basename(filePath, '.json'),
            filePath,
            messages: [],
            raw: null,
            errors: [(err as Error).message],
        };
    }
}

/**
 * Extract messages from a Copilot Chat session JSON.
 * Handles various possible JSON structures.
 */
function extractMessages(raw: unknown): CopilotMessage[] {
    if (!raw || typeof raw !== 'object') {
        return [];
    }

    const obj = raw as Record<string, unknown>;
    
    // Pattern 1: Direct array of messages
    if (Array.isArray(obj)) {
        return normalizeMessages(obj);
    }
    
    // Pattern 2: messages property
    if (Array.isArray(obj.messages)) {
        return normalizeMessages(obj.messages);
    }
    
    // Pattern 3: turns or exchanges property
    if (Array.isArray(obj.turns)) {
        return normalizeMessages(obj.turns);
    }
    if (Array.isArray(obj.exchanges)) {
        return normalizeMessages(obj.exchanges);
    }
    
    // Pattern 4: conversation property
    if (obj.conversation && typeof obj.conversation === 'object') {
        const conv = obj.conversation as Record<string, unknown>;
        if (Array.isArray(conv.messages)) {
            return normalizeMessages(conv.messages);
        }
    }

    // Pattern 5: requests array (Copilot Chat v3 format)
    if (Array.isArray(obj.requests)) {
        const messages: CopilotMessage[] = [];
        for (const request of obj.requests) {
            if (request && typeof request === 'object') {
                const req = request as Record<string, unknown>;
                
                // User message - can be string or object with text property
                if (req.message) {
                    let userText = '';
                    if (typeof req.message === 'string') {
                        userText = req.message;
                    } else if (typeof req.message === 'object' && req.message !== null) {
                        const msgObj = req.message as Record<string, unknown>;
                        if (typeof msgObj.text === 'string') {
                            userText = msgObj.text;
                        }
                    }
                    if (userText) {
                        messages.push({
                            role: 'user',
                            content: userText,
                            timestamp: req.timestamp as number | undefined,
                        });
                    }
                }
                
                // Assistant response - array of response parts
                // Collect all meaningful content from response parts
                if (Array.isArray(req.response)) {
                    const responseParts: string[] = [];
                    
                    for (const part of req.response) {
                        if (part && typeof part === 'object') {
                            const respPart = part as Record<string, unknown>;
                            
                            // Extract content based on kind
                            if (respPart.kind === 'markdownContent' || respPart.kind === 'markdown') {
                                // Main response content
                                if (typeof respPart.content === 'string') {
                                    responseParts.push(respPart.content);
                                }
                            } else if (respPart.kind === 'thinking' && typeof respPart.value === 'string') {
                                // Thinking/reasoning - include for context
                                if (respPart.value) {
                                    responseParts.push(`[Thinking] ${respPart.value}`);
                                }
                            } else if (respPart.kind === 'text' && typeof respPart.content === 'string') {
                                // Plain text response
                                responseParts.push(respPart.content);
                            } else if (typeof respPart.markdownContent === 'string') {
                                // Legacy format
                                responseParts.push(respPart.markdownContent);
                            }
                        }
                    }
                    
                    // Combine all response parts into one assistant message
                    if (responseParts.length > 0) {
                        messages.push({
                            role: 'assistant',
                            content: responseParts.join('\n\n'),
                        });
                    }
                }
            }
        }
        return messages;
    }
    
    return [];
}

/**
 * Normalize an array of messages to our standard format.
 */
function normalizeMessages(arr: unknown[]): CopilotMessage[] {
    const messages: CopilotMessage[] = [];
    
    for (const item of arr) {
        if (!item || typeof item !== 'object') {
            continue;
        }
        
        const obj = item as Record<string, unknown>;
        
        // Extract role (default to 'user' if not specified)
        let role: 'user' | 'assistant' | 'system' = 'user';
        if (obj.role === 'assistant' || obj.role === 'model') {
            role = 'assistant';
        } else if (obj.role === 'system') {
            role = 'system';
        }
        
        // Extract content
        let content = '';
        if (typeof obj.content === 'string') {
            content = obj.content;
        } else if (typeof obj.text === 'string') {
            content = obj.text;
        } else if (typeof obj.message === 'string') {
            content = obj.message;
        }
        
        if (!content) {
            continue;
        }
        
        // Extract timestamp
        const timestamp = typeof obj.timestamp === 'number' ? obj.timestamp : undefined;
        
        // Extract attachments
        let attachments: CopilotAttachment[] | undefined;
        if (Array.isArray(obj.attachments)) {
            attachments = obj.attachments.map(a => {
                if (typeof a === 'object' && a !== null) {
                    return a as CopilotAttachment;
                }
                return { uri: String(a) };
            });
        }
        
        messages.push({
            role,
            content,
            timestamp,
            attachments,
        });
    }
    
    return messages;
}

/**
 * Get metadata for a session file without fully parsing it.
 */
export function getSessionMetadata(filePath: string): SessionMetadata | null {
    try {
        const stat = fs.statSync(filePath);
        const id = path.basename(filePath, '.json');
        
        return {
            session_id: id,
            file_path: filePath,
            mtime: stat.mtime.getTime(),
            size: stat.size,
        };
    } catch {
        return null;
    }
}

/**
 * List all session files in a chatSessions directory.
 */
export function listSessionFiles(chatSessionsPath: string): string[] {
    try {
        if (!fs.existsSync(chatSessionsPath)) {
            return [];
        }
        
        const files = fs.readdirSync(chatSessionsPath);
        return files
            .filter(f => f.endsWith('.json'))
            .map(f => path.join(chatSessionsPath, f));
    } catch {
        return [];
    }
}
