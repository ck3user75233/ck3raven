/**
 * CK3 Lens Status Bar - Minimal status indicator
 * 
 * Shows connection status in the status bar.
 * Clicking opens the sidebar Tools view.
 */

import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

export type ConnectionStatus = 'connected' | 'disconnected';

export interface StatusBarState {
    pythonBridge: ConnectionStatus;
    mcpServer: ConnectionStatus;
}

export class LensStatusBar implements vscode.Disposable {
    private statusBarItem: vscode.StatusBarItem;
    private state: StatusBarState = {
        pythonBridge: 'disconnected',
        mcpServer: 'disconnected'
    };
    private disposables: vscode.Disposable[] = [];

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger
    ) {
        // Create status bar item
        this.statusBarItem = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            100
        );
        this.statusBarItem.command = 'ck3lens.focusToolsView';
        this.updateStatusBar();
        this.statusBarItem.show();

        // Register command to focus the sidebar
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.focusToolsView', () => {
                vscode.commands.executeCommand('ck3lens.agentView.focus');
            })
        );

        this.logger.info('Status bar initialized');
    }

    /**
     * Set Python Bridge connection status
     */
    public setPythonBridgeStatus(status: ConnectionStatus): void {
        this.state.pythonBridge = status;
        this.updateStatusBar();
    }

    /**
     * Set MCP Server connection status
     */
    public setMcpServerStatus(status: ConnectionStatus): void {
        this.state.mcpServer = status;
        this.updateStatusBar();
    }

    private updateStatusBar(): void {
        const bridgeOk = this.state.pythonBridge === 'connected';
        const mcpOk = this.state.mcpServer === 'connected';

        let icon: string;
        let label: string;

        if (bridgeOk && mcpOk) {
            icon = '$(check-all)';
            label = 'CK3 Lens';
        } else if (bridgeOk) {
            icon = '$(check)';
            label = 'CK3 Lens';
        } else if (mcpOk) {
            icon = '$(plug)';
            label = 'CK3 Lens';
        } else {
            icon = '$(circle-slash)';
            label = 'CK3 Lens';
        }

        this.statusBarItem.text = `${icon} ${label}`;
        this.statusBarItem.tooltip = new vscode.MarkdownString(
            `**CK3 Lens**\n\n` +
            `- Python Bridge: ${this.state.pythonBridge}\n` +
            `- MCP Server: ${this.state.mcpServer}\n\n` +
            `Click to open Tools view`
        );

        // Color based on connection status
        if (!bridgeOk && !mcpOk) {
            this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
        } else if (!bridgeOk || !mcpOk) {
            this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        } else {
            this.statusBarItem.backgroundColor = undefined;
        }
    }

    dispose(): void {
        this.statusBarItem.dispose();
        while (this.disposables.length) {
            const d = this.disposables.pop();
            if (d) d.dispose();
        }
    }
}
