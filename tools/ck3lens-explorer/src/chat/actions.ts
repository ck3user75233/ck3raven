/**
 * CK3 Raven Chat Actions
 *
 * Handles tag and action commands for journaling.
 * V1 Brief: basic tagging and journal management.
 */

import * as vscode from 'vscode';
import { JournalWriter } from './journal';
import { Logger } from '../utils/logger';

/**
 * Register action commands
 */
export function registerActionCommands(
    context: vscode.ExtensionContext,
    journal: JournalWriter,
    logger: Logger
): void {
    // Tag current session
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'ck3raven.chat.tagSession',
            async () => {
                const tag = await vscode.window.showInputBox({
                    prompt: 'Enter a tag for this chat session',
                    placeHolder: 'e.g., trait-fix, investigation'
                });

                if (tag) {
                    await journal.logTag(tag);
                    vscode.window.showInformationMessage(`Session tagged: ${tag}`);
                    logger.info(`Session tagged: ${tag}`);
                }
            }
        )
    );

    // Tag with predefined options
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'ck3raven.chat.quickTag',
            async () => {
                const options = [
                    { label: '🔍 investigation', description: 'Research or debugging session' },
                    { label: '🛠️ fix', description: 'Bug fix or patch session' },
                    { label: '✨ feature', description: 'New feature development' },
                    { label: '📚 learning', description: 'Learning or exploration' },
                    { label: '⚠️ issue', description: 'Mark as problematic' },
                    { label: '⭐ important', description: 'Mark as significant' }
                ];

                const selection = await vscode.window.showQuickPick(options, {
                    placeHolder: 'Select a tag for this session'
                });

                if (selection) {
                    // Extract tag without emoji
                    const tag = selection.label.replace(/^[^\w]+\s*/, '');
                    await journal.logTag(tag);
                    vscode.window.showInformationMessage(`Session tagged: ${tag}`);
                    logger.info(`Session tagged: ${tag}`);
                }
            }
        )
    );

    // Log a custom action
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'ck3raven.chat.logAction',
            async (action?: string, payload?: Record<string, unknown>) => {
                // If called programmatically with params
                if (action) {
                    await journal.logAction(action, undefined, payload);
                    logger.info(`Action logged: ${action}`);
                    return;
                }

                // If called from command palette
                const actionInput = await vscode.window.showInputBox({
                    prompt: 'Enter action name',
                    placeHolder: 'e.g., export, bookmark'
                });

                if (actionInput) {
                    await journal.logAction(actionInput);
                    vscode.window.showInformationMessage(`Action logged: ${actionInput}`);
                    logger.info(`Action logged: ${actionInput}`);
                }
            }
        )
    );

    // View current session info
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'ck3raven.chat.sessionInfo',
            () => {
                const sessionId = journal.getCurrentSessionId();
                const sessionFile = journal.getCurrentSessionFile();

                if (!sessionId) {
                    vscode.window.showInformationMessage('No active chat session');
                    return;
                }

                vscode.window.showInformationMessage(
                    `Session: ${sessionId.slice(0, 8)}... | File: ${sessionFile || 'unknown'}`
                );
            }
        )
    );

    // Open journal folder
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'ck3raven.chat.openJournalFolder',
            async () => {
                const folder = journal.getJournalFolder();
                if (folder) {
                    await vscode.commands.executeCommand('revealFileInOS', folder);
                } else {
                    vscode.window.showWarningMessage('Journal folder not available');
                }
            }
        )
    );
}
