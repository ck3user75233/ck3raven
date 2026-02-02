/**
 * Journal Status Bar
 * 
 * Shows "📓 Journal Window: ON" indicator when a window is active.
 */

import * as vscode from 'vscode';
import { WindowManager } from './windowManager';

/**
 * Status bar manager for Journal windows.
 */
export class JournalStatusBar {
    private statusBarItem: vscode.StatusBarItem;
    private windowManager: WindowManager;
    private disposables: vscode.Disposable[] = [];

    constructor(windowManager: WindowManager) {
        this.windowManager = windowManager;

        // Create status bar item (right side, medium priority)
        this.statusBarItem = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            100
        );
        
        this.statusBarItem.command = 'ck3raven.journal.status';
        this.statusBarItem.tooltip = 'Click for Journal status';

        // Subscribe to window state changes
        this.disposables.push(
            windowManager.onDidChangeWindowState(() => this.update())
        );

        // Initial update
        this.update();
    }

    /**
     * Update the status bar based on current window state.
     */
    private update(): void {
        if (this.windowManager.isWindowActive()) {
            this.statusBarItem.text = '$(notebook) Journal: ON';
            this.statusBarItem.backgroundColor = undefined; // Default
            this.statusBarItem.show();
        } else {
            // Hide when no window is active
            this.statusBarItem.hide();
        }
    }

    /**
     * Dispose the status bar.
     */
    public dispose(): void {
        this.statusBarItem.dispose();
        for (const d of this.disposables) {
            d.dispose();
        }
    }
}

/**
 * Create and register the status bar.
 */
export function createJournalStatusBar(windowManager: WindowManager): JournalStatusBar {
    return new JournalStatusBar(windowManager);
}
