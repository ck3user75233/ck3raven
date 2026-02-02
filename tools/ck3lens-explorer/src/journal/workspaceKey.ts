/**
 * Workspace Key Derivation
 * 
 * Derives a stable, unique key for a workspace to scope journal storage.
 * 
 * Priority order:
 * 1. Override from configuration (if set)
 * 2. SHA-256 hash of normalized workspace path
 * 3. Fallback to storageUri segment (if available)
 */

import * as crypto from 'crypto';
import * as path from 'path';
import * as vscode from 'vscode';

/**
 * Derive a workspace key for journal storage scoping.
 * 
 * @param workspaceFolder - The workspace folder to derive key for
 * @param override - Optional override from configuration
 * @returns 16-character hex string (first 64 bits of SHA-256)
 */
export function deriveWorkspaceKey(
    workspaceFolder: vscode.WorkspaceFolder,
    override?: string
): string {
    // Priority 1: Configuration override
    if (override && override.trim().length > 0) {
        return sanitizeKey(override.trim());
    }

    // Priority 2: SHA-256 hash of normalized path
    const normalizedPath = normalizePath(workspaceFolder.uri.fsPath);
    return hashPath(normalizedPath);
}

/**
 * Derive workspace key from the current active workspace.
 * Returns undefined if no workspace is open.
 * 
 * @param override - Optional override from configuration
 */
export function deriveActiveWorkspaceKey(override?: string): string | undefined {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
        return undefined;
    }

    // Use the first workspace folder (primary workspace)
    return deriveWorkspaceKey(folders[0], override);
}

/**
 * Normalize a filesystem path for consistent hashing.
 * 
 * - Converts to lowercase (Windows case-insensitivity)
 * - Uses forward slashes
 * - Removes trailing slashes
 * - Trims whitespace
 */
function normalizePath(fsPath: string): string {
    let normalized = fsPath.trim();
    
    // Lowercase for case-insensitive comparison (Windows)
    normalized = normalized.toLowerCase();
    
    // Normalize separators to forward slashes
    normalized = normalized.replace(/\\/g, '/');
    
    // Remove trailing slash
    if (normalized.endsWith('/')) {
        normalized = normalized.slice(0, -1);
    }
    
    return normalized;
}

/**
 * Hash a normalized path to produce workspace key.
 * Returns first 16 hex characters (64 bits) of SHA-256.
 */
function hashPath(normalizedPath: string): string {
    const hash = crypto.createHash('sha256');
    hash.update(normalizedPath, 'utf8');
    const fullHash = hash.digest('hex');
    
    // Return first 16 characters (64 bits) for reasonable uniqueness
    // with manageable folder names
    return fullHash.substring(0, 16);
}

/**
 * Sanitize a user-provided override key.
 * Ensures it's safe for use as a directory name.
 */
function sanitizeKey(key: string): string {
    // Replace unsafe characters with underscores
    // Allow alphanumeric, hyphens, underscores
    return key.replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 64);
}

/**
 * Get display name for a workspace (for UI and logging).
 */
export function getWorkspaceDisplayName(workspaceFolder: vscode.WorkspaceFolder): string {
    return workspaceFolder.name || path.basename(workspaceFolder.uri.fsPath);
}
