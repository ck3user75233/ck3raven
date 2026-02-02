/**
 * Markdown Export
 * 
 * Converts Copilot Chat sessions to readable Markdown format.
 */

import { CopilotSession, CopilotMessage } from './backends/jsonBackend';

/**
 * Convert a session to Markdown format.
 * 
 * @param session - The session to export
 * @returns Markdown string
 */
export function sessionToMarkdown(session: CopilotSession): string {
    const lines: string[] = [];
    
    // Header
    lines.push(`# Copilot Chat Session: ${session.id}`);
    lines.push('');
    lines.push(`**Session ID:** ${session.id}`);
    lines.push(`**Messages:** ${session.messages.length}`);
    lines.push('');
    lines.push('---');
    lines.push('');
    
    // Messages
    for (let i = 0; i < session.messages.length; i++) {
        const message = session.messages[i];
        lines.push(formatMessage(message, i + 1));
        lines.push('');
    }
    
    return lines.join('\n');
}

/**
 * Format a single message as Markdown.
 */
function formatMessage(message: CopilotMessage, index: number): string {
    const lines: string[] = [];
    
    // Role header
    const roleEmoji = message.role === 'user' ? '👤' : 
                      message.role === 'assistant' ? '🤖' : '⚙️';
    const roleLabel = message.role.charAt(0).toUpperCase() + message.role.slice(1);
    
    lines.push(`## ${roleEmoji} ${roleLabel} (${index})`);
    lines.push('');
    
    // Timestamp if available
    if (message.timestamp) {
        const date = new Date(message.timestamp);
        lines.push(`*${date.toISOString()}*`);
        lines.push('');
    }
    
    // Content
    lines.push(message.content);
    
    // Attachments if any
    if (message.attachments && message.attachments.length > 0) {
        lines.push('');
        lines.push('**Attachments:**');
        for (const attachment of message.attachments) {
            if (attachment.uri) {
                lines.push(`- \`${attachment.uri}\``);
            }
        }
    }
    
    lines.push('');
    lines.push('---');
    
    return lines.join('\n');
}

/**
 * Format session metadata for inclusion in manifest or index.
 */
export function formatSessionSummary(session: CopilotSession): string {
    const userMessages = session.messages.filter(m => m.role === 'user').length;
    const assistantMessages = session.messages.filter(m => m.role === 'assistant').length;
    
    return `${session.id}: ${userMessages} user, ${assistantMessages} assistant messages`;
}
