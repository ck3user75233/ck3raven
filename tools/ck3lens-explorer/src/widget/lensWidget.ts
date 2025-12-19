/**
 * CK3 Lens Widget - Floating status/control overlay
 * 
 * Provides:
 * - Lens enabled/disabled status
 * - Mode switching (ck3lens, ck3raven-dev, ck3creator)
 * - Agent engagement status
 * - MCP connection status
 * - Quick actions
 */

import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

export type LensMode = 'ck3lens' | 'ck3raven-dev' | 'ck3creator' | string;
export type AgentStatus = 'idle' | 'engaged' | 'error';
export type McpStatus = 'connected' | 'disconnected';

export interface Ck3UiState {
    lensEnabled: boolean;
    mode: LensMode;
    agent: { status: AgentStatus; lastError?: string };
    mcp: { status: McpStatus; latencyMs?: number; serverName?: string };
    session: { id: string; startedAt: string };
}

export interface WidgetConfig {
    enabled: boolean;
    anchor: 'bottomRight' | 'bottomLeft' | 'topRight' | 'topLeft';
    opacity: number;
    startCollapsed: boolean;
}

/**
 * Mode definitions with behavioral contracts
 */
export const MODE_DEFINITIONS: Record<string, {
    displayName: string;
    description: string;
    icon: string;
    toolset: string[];
    uiActions: string[];
}> = {
    'ck3lens': {
        displayName: 'CK3 Lens (Compatch)',
        description: 'Mod integration, conflict resolution, virtual merge workflows',
        icon: '$(merge)',
        toolset: ['parsers', 'diff', 'merge', 'resolver', 'on_action', 'localization'],
        uiActions: ['openMergeDashboard', 'runResolver', 'scanConflicts']
    },
    'ck3raven-dev': {
        displayName: 'CK3 Raven Dev',
        description: 'Game-state emulator + toolchain development',
        icon: '$(beaker)',
        toolset: ['indexing', 'sql', 'ast', 'profiling', 'schema', 'migrations'],
        uiActions: ['reindexPlayset', 'openSchemaView', 'runBenchmarks']
    },
    'ck3creator': {
        displayName: 'CK3 Creator',
        description: 'New content creation (events, cultures, traditions)',
        icon: '$(lightbulb)',
        toolset: ['scaffolding', 'validation', 'locgen', 'assets'],
        uiActions: ['createModSkeleton', 'generateEventChain', 'validateContent']
    }
};

export class LensWidget implements vscode.Disposable {
    private statusBarItem: vscode.StatusBarItem;
    private webviewPanel: vscode.WebviewPanel | undefined;
    private state: Ck3UiState;
    private config: WidgetConfig;
    private disposables: vscode.Disposable[] = [];
    private readonly stateChangeEmitter = new vscode.EventEmitter<Ck3UiState>();
    
    public readonly onStateChange = this.stateChangeEmitter.event;

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger
    ) {
        // Initialize state
        this.state = this.loadState();
        this.config = this.loadConfig();

        // Create status bar item (always visible fallback)
        this.statusBarItem = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            100
        );
        this.statusBarItem.command = 'ck3lens.openWidget';
        this.updateStatusBar();
        this.statusBarItem.show();

        // Watch for config changes
        this.disposables.push(
            vscode.workspace.onDidChangeConfiguration((e: vscode.ConfigurationChangeEvent) => {
                if (e.affectsConfiguration('ck3')) {
                    this.config = this.loadConfig();
                    this.updateStatusBar();
                    this.updateWebview();
                }
            })
        );

        // Register commands
        this.registerCommands();

        this.logger.info('Lens Widget initialized');
    }

    private loadState(): Ck3UiState {
        const stored = this.context.globalState.get<Ck3UiState>('ck3lens.uiState');
        return stored || {
            lensEnabled: false,
            mode: 'ck3lens',
            agent: { status: 'idle' },
            mcp: { status: 'disconnected' },
            session: { id: this.generateSessionId(), startedAt: new Date().toISOString() }
        };
    }

    private loadConfig(): WidgetConfig {
        const config = vscode.workspace.getConfiguration('ck3.widget');
        return {
            enabled: config.get<boolean>('enabled', true),
            anchor: config.get<any>('anchor', 'bottomRight'),
            opacity: config.get<number>('opacity', 0.95),
            startCollapsed: config.get<boolean>('startCollapsed', false)
        };
    }

    private generateSessionId(): string {
        return 'S-' + Math.random().toString(36).substring(2, 10);
    }

    private registerCommands(): void {
        // Toggle lens
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.toggleLens', () => {
                this.setLensEnabled(!this.state.lensEnabled);
            })
        );

        // Select mode
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.selectMode', async () => {
                const items = Object.entries(MODE_DEFINITIONS).map(([id, def]) => ({
                    label: `${def.icon} ${def.displayName}`,
                    description: def.description,
                    id
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    placeHolder: 'Select CK3 Lens Mode',
                    title: 'Switch Mode'
                });

                if (selected) {
                    this.setMode(selected.id as LensMode);
                }
            })
        );

        // Toggle agent engagement
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.toggleAgentEngagement', () => {
                const newStatus: AgentStatus = this.state.agent.status === 'engaged' ? 'idle' : 'engaged';
                this.setAgentStatus(newStatus);
            })
        );

        // Open widget panel
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.openWidget', () => {
                this.showWebviewPanel();
            })
        );

        // Hide widget
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.hideWidget', () => {
                this.webviewPanel?.dispose();
            })
        );

        // Open logs
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.openLogs', () => {
                vscode.commands.executeCommand('workbench.action.output.show', 'CK3 Lens');
            })
        );

        // Copy current state
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.copyCurrentState', () => {
                const stateJson = JSON.stringify(this.state, null, 2);
                vscode.env.clipboard.writeText(stateJson);
                vscode.window.showInformationMessage('CK3 Lens state copied to clipboard');
            })
        );

        // MCP reconnect
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.mcp.reconnect', async () => {
                this.setMcpStatus('disconnected');
                // Trigger reconnection logic (handled by session)
                await vscode.commands.executeCommand('ck3lens.initSession');
            })
        );
    }

    /**
     * Set lens enabled state
     */
    public setLensEnabled(enabled: boolean): void {
        this.state.lensEnabled = enabled;
        this.persistState();
        this.updateStatusBar();
        this.updateWebview();
        this.stateChangeEmitter.fire(this.state);
        
        this.logger.info(`Lens ${enabled ? 'enabled' : 'disabled'}`);
        
        if (enabled && vscode.workspace.getConfiguration('ck3.agent').get('autoEngageOnLensEnable', false)) {
            this.setAgentStatus('engaged');
        }
    }

    /**
     * Set current mode
     */
    public setMode(mode: LensMode): void {
        this.state.mode = mode;
        this.persistState();
        this.updateStatusBar();
        this.updateWebview();
        this.stateChangeEmitter.fire(this.state);
        
        this.logger.info(`Mode changed to: ${mode}`);
        vscode.window.showInformationMessage(`Switched to ${MODE_DEFINITIONS[mode]?.displayName || mode} mode`);
    }

    /**
     * Set agent status
     */
    public setAgentStatus(status: AgentStatus, lastError?: string): void {
        this.state.agent = { status, lastError };
        this.persistState();
        this.updateStatusBar();
        this.updateWebview();
        this.stateChangeEmitter.fire(this.state);
        
        this.logger.info(`Agent status: ${status}${lastError ? ` (${lastError})` : ''}`);
    }

    /**
     * Set MCP connection status
     */
    public setMcpStatus(status: McpStatus, latencyMs?: number, serverName?: string): void {
        this.state.mcp = { status, latencyMs, serverName };
        this.persistState();
        this.updateStatusBar();
        this.updateWebview();
        this.stateChangeEmitter.fire(this.state);
    }

    /**
     * Get current state
     */
    public getState(): Ck3UiState {
        return { ...this.state };
    }

    private persistState(): void {
        this.context.globalState.update('ck3lens.uiState', this.state);
    }

    private updateStatusBar(): void {
        const mode = MODE_DEFINITIONS[this.state.mode];
        const modeIcon = mode?.icon || '$(circle)';
        const lensIcon = this.state.lensEnabled ? '$(check)' : '$(circle-slash)';
        const agentIcon = this.state.agent.status === 'engaged' ? '🤖' : 
                         this.state.agent.status === 'error' ? '⚠️' : '💤';
        const mcpIcon = this.state.mcp.status === 'connected' ? '🔗' : '❌';

        this.statusBarItem.text = `${lensIcon} CK3 ${modeIcon} ${agentIcon} ${mcpIcon}`;
        this.statusBarItem.tooltip = new vscode.MarkdownString(
            `**CK3 Lens Status**\n\n` +
            `- Lens: ${this.state.lensEnabled ? 'ON' : 'OFF'}\n` +
            `- Mode: ${mode?.displayName || this.state.mode}\n` +
            `- Agent: ${this.state.agent.status}${this.state.agent.lastError ? ` (${this.state.agent.lastError})` : ''}\n` +
            `- MCP: ${this.state.mcp.status}${this.state.mcp.latencyMs ? ` (${this.state.mcp.latencyMs}ms)` : ''}\n\n` +
            `Click to open widget panel`
        );

        // Color based on state
        if (this.state.agent.status === 'error' || this.state.mcp.status === 'disconnected') {
            this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
        } else if (this.state.agent.status === 'engaged') {
            this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.activeBackground');
        } else {
            this.statusBarItem.backgroundColor = undefined;
        }
    }

    private showWebviewPanel(): void {
        if (this.webviewPanel) {
            this.webviewPanel.reveal();
            return;
        }

        this.webviewPanel = vscode.window.createWebviewPanel(
            'ck3lens.widget',
            'CK3 Lens',
            {
                viewColumn: vscode.ViewColumn.Beside,
                preserveFocus: true
            },
            {
                enableScripts: true,
                retainContextWhenHidden: true
            }
        );

        this.webviewPanel.onDidDispose(() => {
            this.webviewPanel = undefined;
        }, null, this.disposables);

        this.webviewPanel.webview.onDidReceiveMessage(
            (message: { command: string; mode?: string }) => this.handleWebviewMessage(message),
            null,
            this.disposables
        );

        this.updateWebview();
    }

    private handleWebviewMessage(message: any): void {
        switch (message.command) {
            case 'toggleLens':
                this.setLensEnabled(!this.state.lensEnabled);
                break;
            case 'setMode':
                this.setMode(message.mode);
                break;
            case 'toggleAgent':
                vscode.commands.executeCommand('ck3lens.toggleAgentEngagement');
                break;
            case 'openLogs':
                vscode.commands.executeCommand('ck3lens.openLogs');
                break;
            case 'copyState':
                vscode.commands.executeCommand('ck3lens.copyCurrentState');
                break;
            case 'reconnectMcp':
                vscode.commands.executeCommand('ck3lens.mcp.reconnect');
                break;
            case 'openSettings':
                vscode.commands.executeCommand('workbench.action.openSettings', '@ext:ck3-modding.ck3lens-explorer');
                break;
        }
    }

    private updateWebview(): void {
        if (!this.webviewPanel) return;
        this.webviewPanel.webview.html = this.getWebviewHtml();
    }

    private getWebviewHtml(): string {
        const nonce = this.getNonce();
        const mode = MODE_DEFINITIONS[this.state.mode];
        
        const modeOptions = Object.entries(MODE_DEFINITIONS).map(([id, def]) => 
            `<option value="${id}" ${id === this.state.mode ? 'selected' : ''}>${def.displayName}</option>`
        ).join('');

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <title>CK3 Lens Widget</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 16px;
            color: var(--vscode-foreground);
            background: var(--vscode-editor-background);
            min-width: 280px;
        }
        .section {
            margin-bottom: 16px;
            padding: 12px;
            background: var(--vscode-sideBar-background);
            border-radius: 6px;
            border: 1px solid var(--vscode-panel-border);
        }
        .section-title {
            font-weight: bold;
            margin-bottom: 8px;
            font-size: 13px;
            color: var(--vscode-sideBarSectionHeader-foreground);
        }
        .status-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 4px 0;
        }
        .status-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }
        .status-indicator.on { background: #4caf50; }
        .status-indicator.off { background: #9e9e9e; }
        .status-indicator.error { background: #f44336; }
        .status-indicator.engaged { background: #2196f3; animation: pulse 1.5s infinite; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        button {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 8px 16px;
            cursor: pointer;
            border-radius: 4px;
            width: 100%;
            margin: 4px 0;
            font-size: 13px;
        }
        button:hover {
            background: var(--vscode-button-hoverBackground);
        }
        button.secondary {
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        select {
            width: 100%;
            padding: 6px;
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 4px;
        }
        .mode-description {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin-top: 6px;
        }
        .quick-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        .quick-actions button {
            font-size: 12px;
            padding: 6px 8px;
        }
        .health {
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
        }
        .health .latency {
            color: ${this.state.mcp.latencyMs && this.state.mcp.latencyMs > 500 ? '#ff9800' : '#4caf50'};
        }
    </style>
</head>
<body>
    <div class="section">
        <div class="section-title">Lens Status</div>
        <div class="status-row">
            <span class="status-indicator ${this.state.lensEnabled ? 'on' : 'off'}"></span>
            <span>Lens: ${this.state.lensEnabled ? 'ON' : 'OFF'}</span>
        </div>
        <button onclick="toggleLens()">${this.state.lensEnabled ? 'Disable' : 'Enable'} Lens</button>
    </div>

    <div class="section">
        <div class="section-title">Mode</div>
        <select onchange="setMode(this.value)">
            ${modeOptions}
        </select>
        <div class="mode-description">${mode?.description || ''}</div>
    </div>

    <div class="section">
        <div class="section-title">Agent</div>
        <div class="status-row">
            <span class="status-indicator ${this.state.agent.status}"></span>
            <span>Agent: ${this.state.agent.status}${this.state.agent.lastError ? ` - ${this.state.agent.lastError}` : ''}</span>
        </div>
        <button onclick="toggleAgent()">${this.state.agent.status === 'engaged' ? 'Disengage' : 'Engage'} Agent</button>
    </div>

    <div class="section">
        <div class="section-title">Connection</div>
        <div class="status-row">
            <span class="status-indicator ${this.state.mcp.status === 'connected' ? 'on' : 'error'}"></span>
            <span>MCP: ${this.state.mcp.status}</span>
            ${this.state.mcp.latencyMs ? `<span class="health latency">(${this.state.mcp.latencyMs}ms)</span>` : ''}
        </div>
        ${this.state.mcp.serverName ? `<div class="health">Server: ${this.state.mcp.serverName}</div>` : ''}
        ${this.state.mcp.status === 'disconnected' ? '<button class="secondary" onclick="reconnectMcp()">Reconnect</button>' : ''}
    </div>

    <div class="section">
        <div class="section-title">Quick Actions</div>
        <div class="quick-actions">
            <button class="secondary" onclick="openLogs()">📋 Logs</button>
            <button class="secondary" onclick="copyState()">📋 State</button>
            <button class="secondary" onclick="openSettings()">⚙️ Settings</button>
        </div>
    </div>

    <div class="health" style="text-align: center; margin-top: 12px;">
        Session: ${this.state.session.id} | Started: ${new Date(this.state.session.startedAt).toLocaleTimeString()}
    </div>

    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        
        function toggleLens() { vscode.postMessage({ command: 'toggleLens' }); }
        function setMode(mode) { vscode.postMessage({ command: 'setMode', mode }); }
        function toggleAgent() { vscode.postMessage({ command: 'toggleAgent' }); }
        function openLogs() { vscode.postMessage({ command: 'openLogs' }); }
        function copyState() { vscode.postMessage({ command: 'copyState' }); }
        function reconnectMcp() { vscode.postMessage({ command: 'reconnectMcp' }); }
        function openSettings() { vscode.postMessage({ command: 'openSettings' }); }
    </script>
</body>
</html>`;
    }

    private getNonce(): string {
        let text = '';
        const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        for (let i = 0; i < 32; i++) {
            text += possible.charAt(Math.floor(Math.random() * possible.length));
        }
        return text;
    }

    dispose(): void {
        this.statusBarItem.dispose();
        this.webviewPanel?.dispose();
        this.stateChangeEmitter.dispose();
        while (this.disposables.length) {
            const d = this.disposables.pop();
            if (d) d.dispose();
        }
    }
}
