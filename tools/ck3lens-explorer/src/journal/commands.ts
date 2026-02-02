/**
 * Journal Commands
 * 
 * VS Code command registrations for Journal window lifecycle.
 */

import * as vscode from 'vscode';
import { WindowManager } from './windowManager';

/**
 * Register all journal commands.
 * 
 * @param context - Extension context for disposable registration
 * @param windowManager - Window manager instance
 */
export function registerJournalCommands(
    context: vscode.ExtensionContext,
    windowManager: WindowManager
): void {
    // Start Window
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.journal.startWindow', async () => {
            await windowManager.startWindow();
        })
    );

    // Close Window
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.journal.closeWindow', async () => {
            const closed = await windowManager.closeWindow('user_command');
            if (!closed) {
                vscode.window.showInformationMessage('Journal: No active window to close');
            }
        })
    );

    // Status
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.journal.status', () => {
            const status = windowManager.getStatus();
            
            if (!status.active) {
                vscode.window.showInformationMessage(
                    'Journal: No active window. Use "Journal: Start Window" to begin recording.'
                );
                return;
            }

            const lines = [
                `📓 Journal Window Active`,
                ``,
                `Window ID: ${status.windowId}`,
                `Workspace: ${status.workspaceKey}`,
                `Started: ${status.startedAt}`,
                `Baseline Files: ${status.baselineFiles}`,
            ];

            vscode.window.showInformationMessage(lines.join('\n'), { modal: true });
        })
    );

    // Toggle (convenience command)
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3raven.journal.toggle', async () => {
            if (windowManager.isWindowActive()) {
                await windowManager.closeWindow('user_command');
            } else {
                await windowManager.startWindow();
            }
        })
    );
}

/**
 * Get command contributions for package.json.
 * (Reference for manual addition to package.json)
 */
export const JOURNAL_COMMANDS = [
    {
        command: 'ck3raven.journal.startWindow',
        title: 'Journal: Start Window',
        category: 'CK3 Lens',
    },
    {
        command: 'ck3raven.journal.closeWindow',
        title: 'Journal: Close Window',
        category: 'CK3 Lens',
    },
    {
        command: 'ck3raven.journal.status',
        title: 'Journal: Show Status',
        category: 'CK3 Lens',
    },
    {
        command: 'ck3raven.journal.toggle',
        title: 'Journal: Toggle Window',
        category: 'CK3 Lens',
    },
];
