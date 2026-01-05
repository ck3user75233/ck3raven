/**
 * Agent View Provider - Sidebar view for agent status and initialization
 */

import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

export type LensMode = 'ck3lens' | 'ck3raven-dev' | 'none';
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
        description: 'Full CK3 modding - conflict detection, local mod editing',
        icon: 'merge',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Lens agent by calling the ck3_get_mode_instructions tool with mode "ck3lens". Follow the instructions returned to complete initialization.`
    },
    'ck3raven-dev': {
        displayName: 'CK3 Raven Dev',
        shortName: 'Raven',
        description: 'Infrastructure development - Python, MCP server',
        icon: 'beaker',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Raven Dev agent by calling the ck3_get_mode_instructions tool with mode "ck3raven-dev". Follow the instructions returned to complete initialization.`
    }
};

class AgentTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly itemType: 'python-bridge' | 'mcp-server' | 'policy-enforcement' | 'agent' | 'action' | 'info',
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
    private modeFilePath: string | undefined;
    private modeFileWatcher: vscode.FileSystemWatcher | undefined;
    private traceFileWatcher: vscode.FileSystemWatcher | undefined;
    private startupTime: number = Date.now();
    private readonly TRACE_STARTUP_DELAY_MS = 5000; // Don't read stale trace events for 5 seconds

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger,
        private readonly instanceId?: string
    ) {
        // Always start fresh - don't persist mode across sessions
        this.state = this.createFreshState();
        this.registerCommands();
        
        // Set up mode file watching if we have an instance ID
        if (this.instanceId) {
            this.setupModeFileWatcher();
        }
        
        // Watch trace file for mode changes (with instance_id filtering)
        // Delay initial check to avoid reading stale events from previous sessions
        if (this.instanceId) {
            this.setupTraceFileWatcher();
        }
        
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
     * Track when we last saw ck3lens tools available
     */
    private lastToolCount: number = 0;
    private toolsLastSeen: number = 0;
    private readonly TOOL_STALE_THRESHOLD_MS = 60000; // Consider tools stale after 60 seconds without reconfirmation

    /**
     * Check if MCP server is working by checking tool availability.
     * 
     * Note: vscode.lm.invokeTool() requires a valid toolInvocationToken which is only
     * available during an active language model request context. We cannot call it
     * directly from extension code. Instead, we check tool list freshness and 
     * validate the MCP config file exists.
     */
    private async checkMcpConfiguration(): Promise<void> {
        try {
            // Check if ck3lens tools are currently listed
            const allTools = vscode.lm.tools;
            // Tool names use format: mcp_ck3_lens_{instanceId}_ck3_{toolname}
            // Match pattern: starts with mcp_ck3 and contains _ck3_ (our tool prefix)
            const ck3Tools = allTools.filter(tool => 
                tool.name.startsWith('mcp_ck3') && tool.name.includes('_ck3_')
            );
            const now = Date.now();
            
            if (ck3Tools.length === 0) {
                // No tools listed at all
                this.lastToolCount = 0;
                await this.markMcpDisconnected('no tools registered');
                return;
            }

            // Tools are listed - but we need to verify they're fresh
            // If tool count changed, we know VS Code just refreshed the list
            if (ck3Tools.length !== this.lastToolCount) {
                this.toolsLastSeen = now;
                this.lastToolCount = ck3Tools.length;
                this.logger.info(`MCP tools refreshed: ${ck3Tools.length} tools detected`);
            }

            // Dynamic provider: if tools are registered, MCP is working
            // No need to check static config file - tool presence IS the proof

            // If we haven't seen a tool count change in a while, be cautious
            // But still mark as connected if tools exist (VS Code manages the lifecycle)
            const toolsAreFresh = (now - this.toolsLastSeen) < this.TOOL_STALE_THRESHOLD_MS;
            
            if (toolsAreFresh || this.toolsLastSeen === 0) {
                // First check or tools recently refreshed - mark as connected
                this.toolsLastSeen = now; // Initialize on first run
                this.state.mcpServer = { 
                    status: 'connected', 
                    serverName: `ck3lens (${ck3Tools.length} tools)` 
                };
                
                // Check for policy tools
                const hasPolicyTool = ck3Tools.some(t => 
                    t.name.includes('policy') || t.name.includes('validate')
                );
                this.state.policyEnforcement = hasPolicyTool 
                    ? { status: 'connected', message: 'active' }
                    : { status: 'disconnected', message: 'no policy tools found' };
            } else {
                // Tools exist but haven't been refreshed - still report as connected
                // VS Code manages MCP lifecycle, if tools are listed they should work
                this.state.mcpServer = { 
                    status: 'connected', 
                    serverName: `ck3lens (${ck3Tools.length} tools)` 
                };
                
                const hasPolicyTool = ck3Tools.some(t => 
                    t.name.includes('policy') || t.name.includes('validate')
                );
                this.state.policyEnforcement = hasPolicyTool 
                    ? { status: 'connected', message: 'active' }
                    : { status: 'disconnected', message: 'no policy tools found' };
            }
            
            this.logger.debug(`MCP check: ${ck3Tools.length} tools, fresh=${toolsAreFresh}`);
        } catch (error) {
            this.logger.error('MCP status check error:', error);
            await this.markMcpDisconnected('check error');
        }

        this.persistState();
        this.refresh();
    }

    /**
     * Mark MCP as disconnected with a reason
     */
    private async markMcpDisconnected(reason: string): Promise<void> {
        this.state.mcpServer = { status: 'disconnected', serverName: reason };
        this.logger.info(`MCP disconnected: ${reason}`);
        this.state.policyEnforcement = { status: 'disconnected', message: 'MCP offline - policies not enforced!' };
    }

    private loadState(): AgentState {
        // Get stored state
        const stored = this.context.globalState.get<AgentState>('ck3lens.agentState');
        
        // Restore agents from storage, or create default
        let agents: AgentInstance[];
        if (stored?.agents && stored.agents.length > 0) {
            // Restore persisted agents but mark them as needing verification
            agents = stored.agents.map(a => ({
                ...a,
                isLocal: false  // Mark as not locally verified
            }));
            this.logger.info(`Restored ${agents.length} agent(s) from storage`);
        } else {
            // Start with default VS Code agent (no mode)
            agents = [{
                id: this.generateId(),
                mode: 'none' as LensMode,
                initializedAt: new Date().toISOString(),
                label: 'Agent',
                isLocal: false
            }];
        }
        
        return {
            pythonBridge: stored?.pythonBridge || { status: 'disconnected' },
            mcpServer: stored?.mcpServer || { status: 'disconnected' },
            policyEnforcement: stored?.policyEnforcement || { status: 'disconnected' },
            agents: agents,  // Use restored or default agents
            session: { id: this.generateId(), startedAt: new Date().toISOString() }
        };
    }

    private persistState(): void {
        this.context.globalState.update('ck3lens.agentState', this.state);
    }

    /**
     * Create fresh state - always starts with mode 'none'
     * We don't persist mode across sessions because the agent needs to re-initialize
     */
    private createFreshState(): AgentState {
        return {
            pythonBridge: { status: 'disconnected' },
            mcpServer: { status: 'disconnected' },
            policyEnforcement: { status: 'disconnected' },
            agents: [{
                id: this.generateId(),
                mode: 'none' as LensMode,
                initializedAt: new Date().toISOString(),
                label: 'Agent',
                isLocal: true
            }],
            session: { id: this.generateId(), startedAt: new Date().toISOString() }
        };
    }

    /**
     * Watch the instance-specific mode file for real-time updates
     */
    private setupModeFileWatcher(): void {
        const os = require('os');
        const path = require('path');
        const fs = require('fs');
        
        const sanitizedId = this.instanceId!.replace(/[^a-zA-Z0-9_-]/g, '_');
        this.modeFilePath = path.join(os.homedir(), '.ck3raven', `agent_mode_${sanitizedId}.json`);
        
        const modeDir = path.dirname(this.modeFilePath);
        
        // Create directory if needed
        if (!fs.existsSync(modeDir)) {
            fs.mkdirSync(modeDir, { recursive: true });
        }
        
        // Watch for changes to the mode file
        const pattern = new vscode.RelativePattern(modeDir, `agent_mode_${sanitizedId}.json`);
        this.modeFileWatcher = vscode.workspace.createFileSystemWatcher(pattern);
        
        this.modeFileWatcher.onDidChange(() => {
            this.loadModeFromFile();
        });
        
        this.modeFileWatcher.onDidCreate(() => {
            this.loadModeFromFile();
        });
        
        this.disposables.push(this.modeFileWatcher);
        this.logger.info(`Watching mode file: ${this.modeFilePath}`);
    }
    
    /**
     * Load agent mode from the instance-specific file
     */
    private loadModeFromFile(): void {
        const fs = require('fs');
        
        if (!this.modeFilePath || !fs.existsSync(this.modeFilePath)) {
            return;
        }
        
        try {
            const content = fs.readFileSync(this.modeFilePath, 'utf-8');
            const data = JSON.parse(content);
            const mode = data.mode as LensMode;
            
            if (mode && mode !== 'none') {
                this.updateAgentMode(mode);
            } else if (mode === null) {
                // Mode was cleared (extension startup or session end)
                this.updateAgentMode('none');
            }
        } catch (error) {
            this.logger.error('Failed to load mode file:', error);
        }
    }

    /**
     * Watch trace file for mode detection.
     * Uses instance_id filtering to only see events from this VS Code window.
     * Delays initial check to avoid reading stale events from previous sessions.
     */
    private setupTraceFileWatcher(): void {
        const os = require('os');
        const path = require('path');
        const fs = require('fs');
        
        const tracePath = path.join(os.homedir(), '.ck3raven', 'traces', 'ck3lens_trace.jsonl');
        const traceDir = path.dirname(tracePath);
        
        // Create directory if needed
        if (!fs.existsSync(traceDir)) {
            try {
                fs.mkdirSync(traceDir, { recursive: true });
            } catch (e) {
                this.logger.error('Failed to create trace directory', e);
                return;
            }
        }
        
        // Watch trace file for mode_initialized events
        const pattern = new vscode.RelativePattern(traceDir, '*.jsonl');
        this.traceFileWatcher = vscode.workspace.createFileSystemWatcher(pattern);
        
        this.traceFileWatcher.onDidChange(() => {
            this.checkTraceForMode();
        });
        
        this.disposables.push(this.traceFileWatcher);
        this.logger.info(`Watching trace file in: ${traceDir}`);
        
        // NO initial check - wait for trace events from this session only
        // The mode file watcher handles the authoritative state
    }
    
    /**
     * Check trace file for recent mode_initialized events from THIS instance only.
     * Filters by instance_id and ignores events from before startup.
     */
    private checkTraceForMode(): void {
        // Skip if within startup delay - don't read stale events
        const elapsed = Date.now() - this.startupTime;
        if (elapsed < this.TRACE_STARTUP_DELAY_MS) {
            this.logger.debug(`Skipping trace check - within startup delay (${elapsed}ms < ${this.TRACE_STARTUP_DELAY_MS}ms)`);
            return;
        }
        
        if (!this.instanceId) {
            return; // Can't filter without instance ID
        }
        
        const os = require('os');
        const path = require('path');
        const fs = require('fs');
        
        const tracePath = path.join(os.homedir(), '.ck3raven', 'traces', 'ck3lens_trace.jsonl');
        
        if (!fs.existsSync(tracePath)) {
            return;
        }
        
        try {
            const content = fs.readFileSync(tracePath, 'utf-8');
            const lines = content.trim().split('\n').filter((l: string) => l.trim());
            
            // Look for most recent mode_initialized event FROM THIS INSTANCE (check last 50 lines)
            const recentLines = lines.slice(-50);
            for (let i = recentLines.length - 1; i >= 0; i--) {
                try {
                    const event = JSON.parse(recentLines[i]);
                    
                    // CRITICAL: Only process events from this instance
                    if (event.instance_id !== this.instanceId) {
                        continue;
                    }
                    
                    // Also check timestamp - event must be after our startup
                    const eventTime = (event.ts || 0) * 1000; // Convert to ms
                    if (eventTime < this.startupTime) {
                        continue; // Stale event from before this session
                    }
                    
                    if (event.tool === 'ck3lens.mode_initialized') {
                        const mode = event.result?.mode || event.args?.mode;
                        if (mode && (mode === 'ck3lens' || mode === 'ck3raven-dev')) {
                            this.updateAgentMode(mode as LensMode);
                            return;
                        }
                    }
                } catch (e) {
                    // Skip malformed lines
                }
            }
        } catch (error) {
            // Trace file may not exist yet
        }
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

        // Policy Enforcement status - ALWAYS show warning when inactive
        const policyLabel = this.state.policyEnforcement.status === 'connected'
            ? 'Policy Rules: active'
            : 'Policy Rules: ⚠️ INACTIVE';
        const policyItem = new AgentTreeItem(
            policyLabel,
            'policy-enforcement'
        );
        policyItem.iconPath = new vscode.ThemeIcon(
            this.state.policyEnforcement.status === 'connected' ? 'shield' : 'warning',
            this.state.policyEnforcement.status === 'connected'
                ? new vscode.ThemeColor('testing.iconPassed')
                : new vscode.ThemeColor('problemsWarningIcon.foreground')
        );
        // Always show description/warning for policy status
        if (this.state.policyEnforcement.status === 'disconnected') {
            policyItem.description = this.state.policyEnforcement.message || 'policies not enforced!';
            policyItem.tooltip = new vscode.MarkdownString(
                `⚠️ **Policy Enforcement Inactive**\n\n` +
                `Reason: ${this.state.policyEnforcement.message || 'Unknown'}\n\n` +
                `Agent actions are NOT being validated against policy rules. ` +
                `This means the agent may perform actions that violate CK3 modding policies.\n\n` +
                `**To fix:** Ensure the MCP server is running and connected.`
            );
        } else if (this.state.policyEnforcement.message) {
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
     * Update agent mode (called when mode is detected from MCP server or trace)
     * Always updates mode - allows switching between modes
     */
    public updateAgentMode(mode: LensMode): void {
        const primaryAgent = this.state.agents.find(a => !a.label.startsWith('Sub-'));
        if (primaryAgent) {
            if (primaryAgent.mode !== mode) {
                this.logger.info(`Agent mode changed: ${primaryAgent.mode} -> ${mode}`);
                primaryAgent.mode = mode;
                primaryAgent.initializedAt = new Date().toISOString();
                this.persistState();
                this.refresh();
            }
        } else {
            // No agent exists, create one
            const newAgent: AgentInstance = {
                id: this.generateId(),
                mode: mode,
                initializedAt: new Date().toISOString(),
                label: 'Agent',
                isLocal: true
            };
            this.state.agents.unshift(newAgent);
            this.persistState();
            this.refresh();
            this.logger.info(`Agent created with mode: ${mode}`);
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
