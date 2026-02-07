/**
 * CCE Discovery - Locate Copilot Chat Sessions Storage
 * 
 * Chat sessions are stored per-workspace in:
 *   workspaceStorage/{workspace_id}/chatSessions/
 * 
 * NO FALLBACKS: If no workspace is open, discovery fails with a clear error.
 * 
 * SAFETY: All chatSessions access is guarded by isShuttingDown flag.
 * During VS Code shutdown, these functions may cause file lock issues.
 * See: docs/bugs/JOURNAL_EXTRACTOR_CHAT_SESSION_LOSS.md
 */

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { 
    CandidateRoot, 
    DiscoveryResult,
    LOG_CATEGORIES 
} from './types';
import { StructuredLogger } from '../utils/structuredLogger';
import { getIsShuttingDown } from './windowManager';

/** Maximum age (in ms) for "recent activity" ranking - 7 days */
const RECENT_ACTIVITY_THRESHOLD_MS = 7 * 24 * 60 * 60 * 1000;

/** Minimum score to consider a candidate valid */
const MIN_VALID_SCORE = 10;

/**
 * Discovery error codes following Reply System pattern.
 */
export const DISCOVERY_ERRORS = {
    /** No workspace is open - storageUri is undefined */
    NO_WORKSPACE: 'JRN-DISC-E-001',
    /** chatSessions directory does not exist */
    NO_CHAT_SESSIONS_DIR: 'JRN-DISC-E-002',
    /** chatSessions exists but contains no session files */
    NO_SESSION_FILES: 'JRN-DISC-E-003',
    /** Operation blocked during shutdown */
    SHUTDOWN_BLOCKED: 'JRN-DISC-E-004',
} as const;

/**
 * Discover the chatSessions directory for Copilot Chat.
 * 
 * REQUIRES: A workspace must be open (storageUri must exist).
 * NO FALLBACKS: Fails fast with specific error codes.
 * SAFETY: Returns immediately if extension is shutting down.
 * 
 * @param context - VS Code extension context
 * @param logger - Structured logger for discovery events
 * @returns Discovery result with path or specific error code
 */
export async function discoverChatSessions(
    context: vscode.ExtensionContext,
    logger: StructuredLogger
): Promise<DiscoveryResult> {
    // CRITICAL: Block chatSessions access during shutdown
    // This prevents file locking issues with VS Code's workspaceStorage
    if (getIsShuttingDown()) {
        logger.warn(LOG_CATEGORIES.DISCOVERY, 'Discovery blocked during shutdown', {
            error_code: DISCOVERY_ERRORS.SHUTDOWN_BLOCKED,
        });
        return {
            success: false,
            chatSessionsPath: undefined,
            candidates: [],
            error: DISCOVERY_ERRORS.SHUTDOWN_BLOCKED,
            errorMessage: 'Discovery blocked: extension is shutting down',
        };
    }

    logger.info(LOG_CATEGORIES.DISCOVERY, 'Starting chatSessions discovery', {
        storageUri: context.storageUri?.fsPath || 'undefined',
    });

    // REQUIRE workspace - no fallback
    if (!context.storageUri) {
        logger.error(LOG_CATEGORIES.DISCOVERY, 'No workspace open', {
            error_code: DISCOVERY_ERRORS.NO_WORKSPACE,
        });
        return {
            success: false,
            chatSessionsPath: undefined,
            candidates: [],
            error: DISCOVERY_ERRORS.NO_WORKSPACE,
            errorMessage: 'No workspace is open. Journal requires a workspace to find chat sessions.',
        };
    }

    // Derive chatSessions path from storageUri
    // storageUri = workspaceStorage/{workspace_id}/ck3-modding.ck3lens-explorer/
    // chatSessions = workspaceStorage/{workspace_id}/chatSessions/
    const extensionStoragePath = context.storageUri.fsPath;
    const workspaceStorageRoot = path.dirname(extensionStoragePath);
    const chatSessionsPath = path.join(workspaceStorageRoot, 'chatSessions');

    logger.debug(LOG_CATEGORIES.DISCOVERY, 'Checking chatSessions path', {
        extensionStoragePath,
        workspaceStorageRoot,
        chatSessionsPath,
    });

    // Re-check shutdown flag before file system access
    if (getIsShuttingDown()) {
        return {
            success: false,
            chatSessionsPath: undefined,
            candidates: [],
            error: DISCOVERY_ERRORS.SHUTDOWN_BLOCKED,
            errorMessage: 'Discovery blocked: extension is shutting down',
        };
    }

    // Check if directory exists
    if (!fs.existsSync(chatSessionsPath)) {
        logger.error(LOG_CATEGORIES.DISCOVERY, 'chatSessions directory does not exist', {
            error_code: DISCOVERY_ERRORS.NO_CHAT_SESSIONS_DIR,
            path: chatSessionsPath,
        });
        return {
            success: false,
            chatSessionsPath: undefined,
            candidates: [{ path: chatSessionsPath, source: 'api_context', score: 0 }],
            error: DISCOVERY_ERRORS.NO_CHAT_SESSIONS_DIR,
            errorMessage: `Chat sessions directory not found: ${chatSessionsPath}. Have you used Copilot Chat in this workspace?`,
        };
    }

    // Check if directory has session files
    let jsonFiles: string[] = [];
    try {
        const files = fs.readdirSync(chatSessionsPath);
        jsonFiles = files.filter(f => f.endsWith('.json'));
    } catch (err) {
        logger.error(LOG_CATEGORIES.DISCOVERY, 'Cannot read chatSessions directory', {
            error_code: DISCOVERY_ERRORS.NO_CHAT_SESSIONS_DIR,
            path: chatSessionsPath,
            error: (err as Error).message,
        });
        return {
            success: false,
            chatSessionsPath: undefined,
            candidates: [{ path: chatSessionsPath, source: 'api_context', score: 0 }],
            error: DISCOVERY_ERRORS.NO_CHAT_SESSIONS_DIR,
            errorMessage: `Cannot read chat sessions directory: ${(err as Error).message}`,
        };
    }

    if (jsonFiles.length === 0) {
        logger.warn(LOG_CATEGORIES.DISCOVERY, 'chatSessions directory is empty', {
            error_code: DISCOVERY_ERRORS.NO_SESSION_FILES,
            path: chatSessionsPath,
        });
        return {
            success: false,
            chatSessionsPath: undefined,
            candidates: [{ path: chatSessionsPath, source: 'api_context', score: 10 }],
            error: DISCOVERY_ERRORS.NO_SESSION_FILES,
            errorMessage: 'No chat session files found. Start a Copilot Chat conversation first.',
        };
    }

    // Success - found chatSessions with files
    const score = calculateScore(chatSessionsPath, jsonFiles, logger);
    
    logger.info(LOG_CATEGORIES.DISCOVERY, 'Discovery successful', {
        path: chatSessionsPath,
        session_files: jsonFiles.length,
        score,
    });

    return {
        success: true,
        chatSessionsPath,
        candidates: [{ path: chatSessionsPath, source: 'api_context', score }],
        error: undefined,
    };
}

/**
 * Calculate score for a valid chatSessions directory.
 */
function calculateScore(chatSessionsPath: string, jsonFiles: string[], logger: StructuredLogger): number {
    // Abort scoring during shutdown
    if (getIsShuttingDown()) {
        return 0;
    }

    let score = 10; // Base: directory exists
    score += 20; // Has JSON files
    score += 5; // API context source

    // Check for recent activity
    const now = Date.now();
    for (const file of jsonFiles.slice(0, 10)) {
        const filePath = path.join(chatSessionsPath, file);
        try {
            const stat = fs.statSync(filePath);
            if (now - stat.mtime.getTime() < RECENT_ACTIVITY_THRESHOLD_MS) {
                score += 30;
                logger.debug(LOG_CATEGORIES.DISCOVERY, 'Recent activity detected', {
                    path: chatSessionsPath,
                    recent_file: file,
                    mtime: stat.mtime.toISOString(),
                });
                break;
            }
        } catch {
            // Skip files we can't stat
        }
    }

    return score;
}

/**
 * Check if a chatSessions directory is valid and usable.
 * SAFETY: Returns false during shutdown.
 */
export function validateChatSessionsPath(chatSessionsPath: string): boolean {
    if (getIsShuttingDown()) {
        return false;
    }

    if (!fs.existsSync(chatSessionsPath)) {
        return false;
    }

    try {
        const stat = fs.statSync(chatSessionsPath);
        if (!stat.isDirectory()) {
            return false;
        }

        fs.readdirSync(chatSessionsPath);
        return true;
    } catch {
        return false;
    }
}
