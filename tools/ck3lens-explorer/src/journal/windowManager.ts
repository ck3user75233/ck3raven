/**
 * Window Manager
 * 
 * Manages Journal Window lifecycle with one-at-a-time enforcement.
 * 
 * Rules:
 * - Only one window can be active at a time
 * - Starting a new window auto-closes the previous (reason: overlap_new_window)
 * - Extension deactivate auto-closes any active window (reason: deactivate)
 * - Manifest is ALWAYS written on close (JRN-VIS-001)
 */

import * as vscode from 'vscode';
import { 
    WindowState, 
    CloseReason, 
    DiscoveryResult,
    ExtractionResult,
    LOG_CATEGORIES,
} from './types';
import { StructuredLogger } from '../utils/structuredLogger';
import { deriveActiveWorkspaceKey, getWorkspaceDisplayName } from './workspaceKey';
import { discoverChatSessions } from './discovery';
import { 
    initializeStorage, 
    initializeWindow, 
    generateWindowId,
    getWindowPath,
} from './storage';
import { createBaseline } from './baseline';
import { extractWindow } from './extractor';

/**
 * Singleton window manager for the Journal Extractor.
 */
export class WindowManager {
    private activeWindow: WindowState | null = null;
    private context: vscode.ExtensionContext;
    private logger: StructuredLogger;
    private onWindowStateChanged: vscode.EventEmitter<WindowState | null>;

    /** Event fired when window state changes */
    public readonly onDidChangeWindowState: vscode.Event<WindowState | null>;

    constructor(context: vscode.ExtensionContext, logger: StructuredLogger) {
        this.context = context;
        this.logger = logger;
        this.onWindowStateChanged = new vscode.EventEmitter<WindowState | null>();
        this.onDidChangeWindowState = this.onWindowStateChanged.event;
    }

    /**
     * Check if a window is currently active.
     */
    public isWindowActive(): boolean {
        return this.activeWindow !== null;
    }

    /**
     * Get the current active window state (if any).
     */
    public getActiveWindow(): WindowState | null {
        return this.activeWindow;
    }

    /**
     * Start a new journal window.
     * 
     * If a window is already active, it will be closed first with reason 'overlap_new_window'.
     * 
     * @returns The new window state, or null if start failed
     */
    public async startWindow(): Promise<WindowState | null> {
        // Get workspace key
        const workspaceKey = deriveActiveWorkspaceKey();
        if (!workspaceKey) {
            this.logger.warn(LOG_CATEGORIES.WINDOW_START, 'No workspace open', {});
            vscode.window.showWarningMessage('Journal: No workspace is open');
            return null;
        }

        // Close any existing window first
        if (this.activeWindow) {
            await this.closeWindow('overlap_new_window');
        }

        // Discover chatSessions - no fallbacks, fail fast with clear error
        const discovery = await discoverChatSessions(this.context, this.logger);
        if (!discovery.success || !discovery.chatSessionsPath) {
            this.logger.warn(LOG_CATEGORIES.DISCOVERY, 'Discovery failed', {
                error_code: discovery.error,
                error_message: discovery.errorMessage,
            });
            vscode.window.showWarningMessage(
                `Journal [${discovery.error}]: ${discovery.errorMessage}`
            );
            return null;
        }

        // Initialize storage
        initializeStorage(workspaceKey, this.logger);

        // Generate window ID
        const windowId = generateWindowId();
        const outputPath = initializeWindow(workspaceKey, windowId);

        // Create baseline snapshot
        const baseline = createBaseline(discovery.chatSessionsPath);

        // Create window state
        const windowState: WindowState = {
            window_id: windowId,
            workspace_key: workspaceKey,
            started_at: new Date().toISOString(),
            baseline,
            chatSessionsPath: discovery.chatSessionsPath,
            outputPath,
        };

        this.activeWindow = windowState;

        // Log window start
        this.logger.info(LOG_CATEGORIES.WINDOW_START, 'Journal window started', {
            window_id: windowId,
            workspace_key: workspaceKey,
            chat_sessions_path: discovery.chatSessionsPath,
            baseline_files: baseline.size,
        });

        // Fire event
        this.onWindowStateChanged.fire(windowState);

        // Show confirmation
        const workspaceName = vscode.workspace.workspaceFolders?.[0]
            ? getWorkspaceDisplayName(vscode.workspace.workspaceFolders[0])
            : 'workspace';
        vscode.window.showInformationMessage(
            `📓 Journal window started for ${workspaceName}`
        );

        return windowState;
    }

    /**
     * Close the active window and run extraction.
     * 
     * @param reason - Reason for closing
     * @returns Extraction result, or null if no window was active
     */
    public async closeWindow(reason: CloseReason = 'user_command'): Promise<ExtractionResult | null> {
        if (!this.activeWindow) {
            this.logger.debug(LOG_CATEGORIES.WINDOW_END, 'No active window to close', {});
            return null;
        }

        const window = this.activeWindow;
        this.activeWindow = null;

        // Run extraction (writes manifest per JRN-VIS-001)
        let extractionResult: ExtractionResult;
        try {
            extractionResult = await extractWindow(window, reason, this.logger);
        } catch (err) {
            this.logger.error(LOG_CATEGORIES.WINDOW_END, 'Extraction failed', {
                window_id: window.window_id,
                error: (err as Error).message,
            });
            // Create minimal result for failed extraction
            extractionResult = {
                success: false,
                exports: [],
                telemetry: {
                    sessions_scanned: 0,
                    sessions_changed: 0,
                    sessions_exported: 0,
                    extraction_duration_ms: 0,
                },
                errors: [{
                    code: 'JRN-EXT-E-001',
                    message: (err as Error).message,
                    context: { stack: (err as Error).stack },
                }],
            };
        }

        // Log window end
        this.logger.info(LOG_CATEGORIES.WINDOW_END, 'Journal window closed', {
            window_id: window.window_id,
            reason,
            sessions_exported: extractionResult.telemetry.sessions_exported,
            extraction_success: extractionResult.success,
        });

        // Fire event
        this.onWindowStateChanged.fire(null);

        // Show confirmation (only for user-initiated close)
        if (reason === 'user_command') {
            const exported = extractionResult.telemetry.sessions_exported;
            vscode.window.showInformationMessage(
                `📓 Journal window closed: ${exported} session(s) exported`
            );
        }

        return extractionResult;
    }

    /**
     * Get status information about the current window.
     */
    public getStatus(): {
        active: boolean;
        windowId?: string;
        workspaceKey?: string;
        startedAt?: string;
        baselineFiles?: number;
    } {
        if (!this.activeWindow) {
            return { active: false };
        }

        return {
            active: true,
            windowId: this.activeWindow.window_id,
            workspaceKey: this.activeWindow.workspace_key,
            startedAt: this.activeWindow.started_at,
            baselineFiles: this.activeWindow.baseline.size,
        };
    }

    /**
     * Dispose the window manager.
     * Called on extension deactivate - auto-closes any active window.
     */
    public async dispose(): Promise<void> {
        if (this.activeWindow) {
            await this.closeWindow('deactivate');
        }
        this.onWindowStateChanged.dispose();
    }
}

// Singleton instance (set during extension activation)
let windowManagerInstance: WindowManager | null = null;

/**
 * Initialize the window manager singleton.
 * Called during extension activation.
 */
export function initializeWindowManager(
    context: vscode.ExtensionContext,
    logger: StructuredLogger
): WindowManager {
    windowManagerInstance = new WindowManager(context, logger);
    return windowManagerInstance;
}

/**
 * Get the window manager singleton.
 * Throws if not initialized.
 */
export function getWindowManager(): WindowManager {
    if (!windowManagerInstance) {
        throw new Error('WindowManager not initialized');
    }
    return windowManagerInstance;
}
