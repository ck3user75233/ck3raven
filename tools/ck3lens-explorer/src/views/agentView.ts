/**
 * Agent View Provider - Sidebar view for agent status and initialization
 */

import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

export type LensMode = 'ck3lens' | 'ck3raven-dev' | 'ck3creator' | 'none';
export type ConnectionStatus = 'connected' | 'disconnected';

export interface AgentInstance {
    id: string;
    mode: LensMode;
    initializedAt: string;
    label: string;
    isLocal?: boolean;
    lastActivity?: string;
    lastActivityTime?: string;
}

export interface AgentState {
    pythonBridge: { status: ConnectionStatus; latencyMs?: number };
    mcpServer: { status: ConnectionStatus; serverName?: string };
    policyEnforcement: { status: ConnectionStatus; message?: string };
    agents: AgentInstance[];
    session: { id: string; startedAt: string };
}

/**
 * Mode definitions with behavioral contracts
 */
export const MODE_DEFINITIONS: Record<string, {
    displayName: string;
    shortName: string;
    description: string;
    icon: string;
    initPrompt: string;
}> = {
    'ck3lens': {
        displayName: 'CK3 Lens',
        shortName: 'Lens',
        description: 'Full CK3 modding - conflict detection, live file editing',
        icon: 'merge',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Lens agent by calling the ck3_get_mode_instructions tool with mode "ck3lens-live". Follow the instructions returned to complete initialization.`
    },
    'ck3raven-dev': {
        displayName: 'CK3 Raven Dev',
        shortName: 'Raven',
        description: 'Infrastructure development - Python, MCP server',
        icon: 'beaker',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Raven Dev agent by calling the ck3_get_mode_instructions tool with mode "ck3raven-dev". Follow the instructions returned to complete initialization.`
    },
    'ck3creator': {
        displayName: 'CK3 Creator',
        shortName: 'Creator',
        description: 'New content creation - experimental',
        icon: 'lightbulb',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Creator agent by calling the ck3_get_mode_instructions tool with mode "ck3creator". Follow the instructions returned to complete initialization.`
    }
};

class AgentTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly itemType: 'python-bridge' | 'mcp-server' | 'agent' | 'action' | 'info',
        public readonly collapsibleState: vscode.TreeItemCollapsibleState = vscode.TreeItemCollapsibleState.None,
        public readonly agent?: AgentInstance,
        public readonly actionCommand?: string
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;
        this.setupItem();
    }

    private setupItem(): void {
        switch (this.itemType) {
            case 'python-bridge':
            case 'mcp-server':
                // Icon set by caller based on status
                break;
            case 'agent':
                if (this.agent) {
                    const modeDef = MODE_DEFINITIONS[this.agent.mode];
                    if (this.agent.mode === 'none') {
                        this.iconPath = new vscode.ThemeIcon('account');
                        this.description = 'initialized by VS Code';
                    } else {
                        this.iconPath = new vscode.ThemeIcon(modeDef?.icon || 'account');
                        this.description = modeDef?.shortName || this.agent.mode;
                    }
                    this.tooltip = new vscode.MarkdownString(
                        `**${this.label}**\n\n` +
                        `Mode: ${this.agent.mode === 'none' ? 'initialized by VS Code' : modeDef?.displayName || this.agent.mode}\n\n` +
                        (this.agent.lastActivity ? `Last activity: ${this.agent.lastActivity}` : '')
                    );
                }
                break;
            case 'action':
                if (this.actionCommand) {
                    this.command = {
                        command: this.actionCommand,
                        title: this.label
                    };
                }
                break;
            case 'info':
                this.iconPath = new vscode.ThemeIcon('info');
                break;
        }
    }
}

export class AgentViewProvider implements vscode.TreeDataProvider<AgentTreeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<AgentTreeItem | undefined | null | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private state: AgentState;
    private disposables: vscode.Disposable[] = [];
    private mcpMonitorInterval: NodeJS.Timeout | undefined;

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger
    ) {
        this.state = this.loadState();
        this.registerCommands();
        
        // Check MCP configuration on startup
        this.checkMcpConfiguration();
        
        // Start ongoing MCP monitoring (every 30 seconds)
        this.startMcpMonitoring();
    }

    /**
     * Start periodic MCP server health monitoring.
     */
    private startMcpMonitoring(): void {
        // Check every 30 seconds
        this.mcpMonitorInterval = setInterval(() => {
            this.checkMcpConfiguration();
        }, 30000);
        
        // Also add to disposables for cleanup
        this.disposables.push({
            dispose: () => {
                if (this.mcpMonitorInterval) {
                    clearInterval(this.mcpMonitorInterval);
                }
            }
        });
    }

    /**
     * Check if MCP server is working by actually calling it
     */
    private async checkMcpConfiguration(): Promise<void> {
        const fs = require('fs');
        const path = require('path');
        const os = require('os');
        const { spawn } = require('child_process');

        // First check if config exists
        const possiblePaths = [
            process.env.APPDATA ? path.join(process.env.APPDATA, 'Code', 'User', 'mcp.json') : null,
            path.join(os.homedir(), 'AppData', 'Roaming', 'Code', 'User', 'mcp.json'),
        ].filter(Boolean);

        let serverPath: string | null = null;

        for (const mcpConfigPath of possiblePaths) {
            try {
                if (mcpConfigPath && fs.existsSync(mcpConfigPath)) {
                    let content = fs.readFileSync(mcpConfigPath, 'utf-8');
                    // Strip BOM if present
                    if (content.charCodeAt(0) === 0xFEFF) {
                        content = content.slice(1);
                    }
                    const config = JSON.parse(content);
                    
                    if (config.servers?.ck3lens?.args?.[0]) {
                        serverPath = config.servers.ck3lens.args[0];
                        this.logger.info(`Found MCP config at ${mcpConfigPath}: ${serverPath}`);
                        break;
                    }
                }
            } catch (error) {
                this.logger.debug(`MCP config check failed for ${mcpConfigPath}: ${error}`);
            }
        }

        if (!serverPath) {
            this.state.mcpServer = { status: 'disconnected', serverName: 'not configured' };
            this.logger.info('No MCP configuration found');
            this.persistState();
            this.refresh();
            return;
        }

        // Test the MCP server by spawning it and sending a ping
        this.logger.info(`Testing MCP server at: ${serverPath}`);
        
        try {
            const result = await this.testMcpServer(serverPath);
            if (result.success) {
                this.state.mcpServer = { status: 'connected', serverName: 'ck3lens' };
                this.logger.info('MCP server responding');
                
                // Also check policy enforcement status via MCP
                await this.checkPolicyStatus(serverPath);
            } else {
                this.state.mcpServer = { status: 'disconnected', serverName: result.error || 'failed' };
                this.state.policyEnforcement = { status: 'disconnected', message: 'MCP offline' };
                this.logger.error('MCP server test failed:', result.error);
            }
        } catch (error) {
            this.state.mcpServer = { status: 'disconnected', serverName: 'error' };
            this.state.policyEnforcement = { status: 'disconnected', message: 'MCP error' };
            this.logger.error('MCP server test error:', error);
        }

        this.persistState();
        this.refresh();
    }

    /**
     * Check policy enforcement status by calling the MCP server's policy health endpoint
     */
    private async checkPolicyStatus(serverPath: string): Promise<void> {
        const { spawn } = require('child_process');
        const path = require('path');
        const fs = require('fs');

        const serverDir = path.dirname(serverPath);
        
        // Find Python
        let pythonPath = 'python';
        const venvPython = path.join(serverDir, '..', '..', '..', '.venv', 'Scripts', 'python.exe');
        if (fs.existsSync(venvPython)) {
            pythonPath = venvPython;
        }

        return new Promise((resolve) => {
            const proc = spawn(pythonPath, [serverPath], {
                cwd: serverDir,
                stdio: ['pipe', 'pipe', 'pipe']
            });

            let stdout = '';
            let resolved = false;

            const timeout = setTimeout(() => {
                if (!resolved) {
                    resolved = true;
                    proc.kill();
                    // Couldn't determine policy status
                    this.state.policyEnforcement = { status: 'disconnected', message: 'timeout' };
                    resolve();
                }
            }, 5000);

            proc.stdout.on('data', (data: Buffer) => {
                stdout += data.toString();
                
                // Look for policy health response
                if (stdout.includes('"healthy"')) {
                    if (!resolved) {
                        resolved = true;
                        clearTimeout(timeout);
                        proc.kill();
                        
                        try {
                            // Parse JSONRPC response
                            const lines = stdout.split('\n');
                            for (const line of lines) {
                                if (line.includes('"healthy"')) {
                                    const match = line.match(/\{[^{}]*"healthy"[^{}]*\}/);
                                    if (match) {
                                        const result = JSON.parse(match[0]);
                                        if (result.healthy === true) {
                                            this.state.policyEnforcement = { status: 'connected', message: 'active' };
                                            this.logger.info('Policy enforcement is active');
                                        } else {
                                            this.state.policyEnforcement = { status: 'disconnected', message: result.error || 'unhealthy' };
                                            this.logger.info('Policy enforcement is inactive:', result.error);
                                        }
                                        resolve();
                                        return;
                                    }
                                }
                            }
                        } catch (e) {
                            this.logger.debug('Failed to parse policy response');
                        }
                        
                        // Default if parsing fails
                        this.state.policyEnforcement = { status: 'connected', message: 'unknown' };
                        resolve();
                    }
                }
            });

            proc.on('error', () => {
                if (!resolved) {
                    resolved = true;
                    clearTimeout(timeout);
                    this.state.policyEnforcement = { status: 'disconnected', message: 'error' };
                    resolve();
                }
            });

            // Send MCP request to check policy status
            const policyRequest = {
                jsonrpc: '2.0',
                id: 2,
                method: 'tools/call',
                params: {
                    name: 'ck3_get_policy_status',
                    arguments: {}
                }
            };

            try {
                proc.stdin.write(JSON.stringify(policyRequest) + '\n');
            } catch (e) {
                // stdin might be closed
            }
        });
    }

    /**
     * Test MCP server by spawning it and sending an initialize request
     */
    private testMcpServer(serverPath: string): Promise<{ success: boolean; error?: string }> {
        return new Promise((resolve) => {
            const { spawn } = require('child_process');
            const path = require('path');
            const fs = require('fs');

            const serverDir = path.dirname(serverPath);
            
            // Try to find the correct Python - check for venv first
            // From ck3lens_mcp, go up 3 levels: ck3lens_mcp -> tools -> ck3raven -> AI Workspace
            let pythonPath = 'python';
            const venvPython = path.join(serverDir, '..', '..', '..', '.venv', 'Scripts', 'python.exe');
            this.logger.info(`Looking for venv at: ${venvPython}`);
            if (fs.existsSync(venvPython)) {
                pythonPath = venvPython;
                this.logger.info(`Using venv Python: ${venvPython}`);
            } else {
                this.logger.info(`Venv not found at ${venvPython}, falling back to system python`);
            }

            this.logger.info(`Spawning: ${pythonPath} ${serverPath}`);
            
            const proc = spawn(pythonPath, [serverPath], {
                cwd: serverDir,
                stdio: ['pipe', 'pipe', 'pipe']
            });

            let stdout = '';
            let stderr = '';
            let resolved = false;

            const timeout = setTimeout(() => {
                if (!resolved) {
                    resolved = true;
                    proc.kill();
                    // If we got here without error, the server started successfully
                    if (stderr.includes('Error') || stderr.includes('Traceback')) {
                        resolve({ success: false, error: 'startup error' });
                    } else {
                        resolve({ success: true });
                    }
                }
            }, 3000);

            proc.stdout.on('data', (data: Buffer) => {
                stdout += data.toString();
            });

            proc.stderr.on('data', (data: Buffer) => {
                stderr += data.toString();
                // MCP servers often log to stderr, check for actual errors
                if (stderr.includes('Traceback') || stderr.includes('ImportError') || stderr.includes('ModuleNotFoundError')) {
                    if (!resolved) {
                        resolved = true;
                        clearTimeout(timeout);
                        proc.kill();
                        resolve({ success: false, error: 'import error' });
                    }
                }
            });

            proc.on('error', (err: Error) => {
                if (!resolved) {
                    resolved = true;
                    clearTimeout(timeout);
                    resolve({ success: false, error: err.message });
                }
            });

            proc.on('exit', (code: number) => {
                if (!resolved) {
                    resolved = true;
                    clearTimeout(timeout);
                    if (code === 0 || code === null) {
                        resolve({ success: true });
                    } else {
                        resolve({ success: false, error: `exit code ${code}` });
                    }
                }
            });

            // Send MCP initialize request
            const initRequest = {
                jsonrpc: '2.0',
                id: 1,
                method: 'initialize',
                params: {
                    protocolVersion: '2024-11-05',
                    capabilities: {},
                    clientInfo: { name: 'ck3lens-test', version: '1.0.0' }
                }
            };

            try {
                proc.stdin.write(JSON.stringify(initRequest) + '\n');
            } catch (e) {
                // stdin might be closed already
            }
        });
    }

    private loadState(): AgentState {
        // Always start fresh on extension activation
        // Agent mode can only be determined by explicit initialization or trace detection
        // Don't persist agent mode across reloads since we can't verify it's still valid
        
        // Start with default VS Code agent (no mode)
        const defaultAgent: AgentInstance = {
            id: this.generateId(),
            mode: 'none',
            initializedAt: new Date().toISOString(),
            label: 'Agent',
            isLocal: false
        };
        
        // Get connection status from stored state (these can persist)
        const stored = this.context.globalState.get<AgentState>('ck3lens.agentState');
        
        return {
            pythonBridge: stored?.pythonBridge || { status: 'disconnected' },
            mcpServer: stored?.mcpServer || { status: 'disconnected' },
            policyEnforcement: stored?.policyEnforcement || { status: 'disconnected' },
            agents: [defaultAgent],  // Always reset to default agent
            session: { id: this.generateId(), startedAt: new Date().toISOString() }
        };
    }

    private persistState(): void {
        this.context.globalState.update('ck3lens.agentState', this.state);
    }

    private generateId(): string {
        return Math.random().toString(36).substring(2, 10);
    }

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    /**
     * Public method to re-check MCP server status.
     * Called by refresh commands.
     */
    public async recheckMcpStatus(): Promise<void> {
        this.logger.info('Re-checking MCP server status...');
        await this.checkMcpConfiguration();
    }

    getTreeItem(element: AgentTreeItem): vscode.TreeItem {
        return element;
    }

    getChildren(element?: AgentTreeItem): Thenable<AgentTreeItem[]> {
        if (element) {
            return Promise.resolve([]);
        }

        const items: AgentTreeItem[] = [];

        // Python Bridge status
        const bridgeItem = new AgentTreeItem(
            `Python Bridge: ${this.state.pythonBridge.status}`,
            'python-bridge'
        );
        bridgeItem.iconPath = new vscode.ThemeIcon(
            this.state.pythonBridge.status === 'connected' ? 'check' : 'close',
            this.state.pythonBridge.status === 'connected' 
                ? new vscode.ThemeColor('testing.iconPassed')
                : new vscode.ThemeColor('testing.iconFailed')
        );
        if (this.state.pythonBridge.latencyMs) {
            bridgeItem.description = `${this.state.pythonBridge.latencyMs}ms`;
        }
        items.push(bridgeItem);

        // MCP Server status (actually tests the server)
        const mcpLabel = this.state.mcpServer.status === 'connected' 
            ? 'MCP Server: connected'
            : 'MCP Server: disconnected';
        const mcpItem = new AgentTreeItem(
            mcpLabel,
            'mcp-server'
        );
        mcpItem.iconPath = new vscode.ThemeIcon(
            this.state.mcpServer.status === 'connected' ? 'plug' : 'debug-disconnect',
            this.state.mcpServer.status === 'connected' 
                ? new vscode.ThemeColor('testing.iconPassed')
                : new vscode.ThemeColor('testing.iconFailed')
        );
        if (this.state.mcpServer.serverName && this.state.mcpServer.status === 'disconnected') {
            mcpItem.description = this.state.mcpServer.serverName;
        }
        items.push(mcpItem);

        // Policy Enforcement status
        const policyLabel = this.state.policyEnforcement.status === 'connected'
            ? 'Policy Rules: active'
            : 'Policy Rules: inactive';
        const policyItem = new AgentTreeItem(
            policyLabel,
            'policy-enforcement'
        );
        policyItem.iconPath = new vscode.ThemeIcon(
            this.state.policyEnforcement.status === 'connected' ? 'shield' : 'warning',
            this.state.policyEnforcement.status === 'connected'
                ? new vscode.ThemeColor('testing.iconPassed')
                : new vscode.ThemeColor('testing.iconFailed')
        );
        if (this.state.policyEnforcement.message && this.state.policyEnforcement.status === 'disconnected') {
            policyItem.description = this.state.policyEnforcement.message;
        }
        items.push(policyItem);

        // Agents
        if (this.state.agents.length === 0) {
            // No agents - show initialize button
            const initItem = new AgentTreeItem(
                'Initialize Agent',
                'action',
                vscode.TreeItemCollapsibleState.None,
                undefined,
                'ck3lens.agent.initialize'
            );
            initItem.iconPath = new vscode.ThemeIcon('add');
            items.push(initItem);
        } else {
            // Show agents
            for (const agent of this.state.agents) {
                const modeLabel = agent.mode === 'none'
                    ? 'Agent'
                    : `Agent - ${MODE_DEFINITIONS[agent.mode]?.shortName || agent.mode}`;
                
                const agentItem = new AgentTreeItem(
                    modeLabel,
                    'agent',
                    vscode.TreeItemCollapsibleState.None,
                    agent
                );
                items.push(agentItem);
            }

            // Add sub-agent action
            const addSubItem = new AgentTreeItem(
                '+ Add Sub-agent',
                'action',
                vscode.TreeItemCollapsibleState.None,
                undefined,
                'ck3lens.agent.addSubAgent'
            );
            addSubItem.iconPath = new vscode.ThemeIcon('add');
            items.push(addSubItem);
        }

        return Promise.resolve(items);
    }

    private registerCommands(): void {
        // Initialize agent (default mode)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.agent.initialize', () => {
                this.initializeAgent();
            })
        );

        // Initialize with specific mode
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.agent.initializeWithMode', async () => {
                const items = Object.entries(MODE_DEFINITIONS).map(([id, def]) => ({
                    label: def.displayName,
                    description: def.description,
                    id
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    placeHolder: 'Select agent mode',
                    title: 'Initialize Agent with Mode'
                });

                if (selected) {
                    await this.initializeAgentWithMode(selected.id as LensMode);
                }
            })
        );

        // Re-initialize agent (context menu)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.agent.reinitialize', async (item: AgentTreeItem) => {
                if (item.agent) {
                    const items = Object.entries(MODE_DEFINITIONS).map(([id, def]) => ({
                        label: def.displayName,
                        description: def.description,
                        id
                    }));

                    const selected = await vscode.window.showQuickPick(items, {
                        placeHolder: 'Select new mode',
                        title: 'Re-initialize Agent'
                    });

                    if (selected) {
                        await this.initializeAgentWithMode(selected.id as LensMode);
                    }
                }
            })
        );

        // Add sub-agent
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.agent.addSubAgent', async () => {
                const items = Object.entries(MODE_DEFINITIONS).map(([id, def]) => ({
                    label: def.displayName,
                    description: def.description,
                    id
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    placeHolder: 'Select sub-agent mode',
                    title: 'Add Sub-agent'
                });

                if (selected) {
                    await this.addSubAgent(selected.id as LensMode);
                }
            })
        );

        // Clear all agents (reset to default)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.agent.clearAll', () => {
                // Reset to default VS Code agent (not initialized with a mode)
                const defaultAgent: AgentInstance = {
                    id: this.generateId(),
                    mode: 'none',
                    initializedAt: new Date().toISOString(),
                    label: 'Agent',
                    isLocal: false
                };
                this.state.agents = [defaultAgent];
                this.persistState();
                this.refresh();
                this.logger.info('All agents cleared');
            })
        );
    }

    /**
     * Initialize agent in default mode
     */
    private initializeAgent(): void {
        const newAgent: AgentInstance = {
            id: this.generateId(),
            mode: 'none',
            initializedAt: new Date().toISOString(),
            label: 'Agent',
            isLocal: true
        };

        // Replace existing primary agent
        this.state.agents = this.state.agents.filter(a => a.label.startsWith('Sub-'));
        this.state.agents.unshift(newAgent);

        this.persistState();
        this.refresh();
        this.logger.info('Agent initialized in default mode');
    }

    /**
     * Initialize agent with specific mode
     */
    private async initializeAgentWithMode(mode: LensMode): Promise<void> {
        const modeDef = MODE_DEFINITIONS[mode];
        if (!modeDef) return;

        const newAgent: AgentInstance = {
            id: this.generateId(),
            mode: mode,
            initializedAt: new Date().toISOString(),
            label: 'Agent',
            isLocal: true
        };

        // Replace existing primary agent
        this.state.agents = this.state.agents.filter(a => a.label.startsWith('Sub-'));
        this.state.agents.unshift(newAgent);

        this.persistState();
        this.refresh();

        // Open chat with initialization prompt
        await vscode.commands.executeCommand('workbench.action.chat.open', {
            query: modeDef.initPrompt
        });

        vscode.window.showInformationMessage(
            `${modeDef.shortName} mode: Press Enter to send the initialization prompt`
        );
    }

    /**
     * Add a sub-agent
     */
    private async addSubAgent(mode: LensMode): Promise<void> {
        const modeDef = MODE_DEFINITIONS[mode];
        if (!modeDef) return;

        const subAgentNum = this.state.agents.filter(a => a.label.startsWith('Sub-')).length + 1;

        const newAgent: AgentInstance = {
            id: this.generateId(),
            mode: mode,
            initializedAt: new Date().toISOString(),
            label: `Sub-Agent ${subAgentNum}`,
            isLocal: true
        };

        this.state.agents.push(newAgent);
        this.persistState();
        this.refresh();

        // Create new chat with initialization prompt
        await vscode.commands.executeCommand('workbench.action.chat.newChat');
        await new Promise(resolve => setTimeout(resolve, 100));
        await vscode.commands.executeCommand('workbench.action.chat.open', {
            query: modeDef.initPrompt
        });

        vscode.window.showInformationMessage(
            `Sub-agent ${modeDef.shortName}: Press Enter to send the initialization prompt (new chat created)`
        );
    }

    /**
     * Set Python Bridge connection status
     */
    public setPythonBridgeStatus(status: ConnectionStatus, latencyMs?: number): void {
        this.state.pythonBridge = { status, latencyMs };
        this.persistState();
        this.refresh();
    }

    /**
     * Set MCP Server connection status
     */
    public setMcpServerStatus(status: ConnectionStatus, serverName?: string): void {
        this.state.mcpServer = { status, serverName };
        this.persistState();
        this.refresh();
    }

    /**
     * Update agent mode (called when mode is detected from trace)
     */
    public updateAgentMode(mode: LensMode): void {
        const primaryAgent = this.state.agents.find(a => !a.label.startsWith('Sub-'));
        if (primaryAgent && primaryAgent.mode === 'none') {
            primaryAgent.mode = mode;
            primaryAgent.initializedAt = new Date().toISOString();
            this.persistState();
            this.refresh();
            this.logger.info(`Agent mode updated to: ${mode}`);
        }
    }

    /**
     * Get current state
     */
    public getState(): AgentState {
        return { ...this.state };
    }

    dispose(): void {
        while (this.disposables.length) {
            const d = this.disposables.pop();
            if (d) d.dispose();
        }
    }
}
