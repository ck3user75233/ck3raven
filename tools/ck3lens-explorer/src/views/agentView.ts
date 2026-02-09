/**
 * Agent View Provider - Sidebar view for agent status and initialization
 */

import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

export type LensMode = 'ck3lens' | 'ck3raven-dev' | 'none' | 'initializing';
export type ConnectionStatus = 'connected' | 'disconnected';
export type PathsStatus = 'healthy' | 'warnings' | 'errors' | 'unchecked';

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
    pathsDoctor: { status: PathsStatus; errorCount: number; warnCount: number; configPath?: string };
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
        initPrompt: `Call ck3_get_mode_instructions(mode="ck3lens") to initialize.`
    },
    'ck3raven-dev': {
        displayName: 'CK3 Raven Dev',
        shortName: 'Raven',
        description: 'Infrastructure development - Python, MCP server',
        icon: 'beaker',
        initPrompt: `Call ck3_get_mode_instructions(mode="ck3raven-dev") to initialize.`
    }
};

/**
 * Generate initialization prompt with MIT token.
 * 
 * MIT (Mode Initialization Token) is required for mode initialization.
 * Instance ID is for debugging only - tool names are mcp_ck3_lens_ck3_* (no instance prefix).
 */
export function generateInitPrompt(mode: LensMode, instanceId: string | undefined, mitToken: string | undefined): string {
    const modeDef = MODE_DEFINITIONS[mode];
    if (!modeDef) {
        return '';
    }
    
    // Single-line prompt with embedded token - no redundancy
    if (mitToken) {
        const call = modeDef.initPrompt.replace(')', `, mit_token="${mitToken}")`);
        const instanceSuffix = instanceId ? ` [${instanceId}]` : '';
        return `${call}${instanceSuffix}\n`;
    }
    
    return `${modeDef.initPrompt}\n`;
}

class AgentTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly itemType: 'paths-doctor' | 'mcp-server' | 'policy-enforcement' | 'agent' | 'action' | 'info' | 'instance-id',
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
            case 'paths-doctor':
                // Set command for click handler
                if (this.actionCommand) {
                    this.command = {
                        command: this.actionCommand,
                        title: this.label
                    };
                }
                break;
            case 'mcp-server':
                // Icon set by caller based on status
                break;
            case 'agent':
                if (this.agent) {
                    const modeDef = MODE_DEFINITIONS[this.agent.mode];
                    if (this.agent.mode === 'none') {
                        this.iconPath = new vscode.ThemeIcon('account');
                        this.description = 'initialized by VS Code';
                    } else if (this.agent.mode === 'initializing') {
                        this.iconPath = new vscode.ThemeIcon('sync~spin');
                        this.description = 'verifying...';
                    } else {
                        this.iconPath = new vscode.ThemeIcon(modeDef?.icon || 'account');
                        this.description = modeDef?.shortName || this.agent.mode;
                    }
                    // Build tooltip text based on mode
                    let modeText: string;
                    if (this.agent.mode === 'none') {
                        modeText = 'initialized by VS Code';
                    } else if (this.agent.mode === 'initializing') {
                        modeText = 'Initializing... awaiting MCP confirmation';
                    } else {
                        modeText = modeDef?.displayName || this.agent.mode;
                    }
                    this.tooltip = new vscode.MarkdownString(
                        `**${this.label}**\n\n` +
                        `Mode: ${modeText}\n\n` +
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
            case 'instance-id':
                this.iconPath = new vscode.ThemeIcon('key');
                // Set command from actionCommand parameter
                if (this.actionCommand) {
                    this.command = {
                        command: this.actionCommand,
                        title: this.label
                    };
                }
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

    // Track last state signature to avoid unnecessary refreshes (prevents listener leak)
    private _lastStateSignature: string = '';

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger,
        private readonly instanceId?: string,
        private readonly getMitToken?: () => string
    ) {
        console.log('[CK3RAVEN] AgentViewProvider constructor ENTER');
        // Always start fresh - don't persist mode across sessions
        this.state = this.createFreshState();
        console.log('[CK3RAVEN] AgentViewProvider after createFreshState');
        
        // Add the event emitter to disposables for proper cleanup
        this.disposables.push(this._onDidChangeTreeData);
        this.registerCommands();
        console.log('[CK3RAVEN] AgentViewProvider after registerCommands');
        
        // Set up mode file watching if we have an instance ID
        if (this.instanceId) {
            this.setupModeFileWatcher();
        }
        console.log('[CK3RAVEN] AgentViewProvider setupModeFileWatcher done');
        
        // Watch trace file for mode changes (with instance_id filtering)
        if (this.instanceId) {
            this.setupTraceFileWatcher();
        }
        console.log('[CK3RAVEN] AgentViewProvider setupTraceFileWatcher done');
        
        // Check MCP configuration on startup
        this.checkMcpConfiguration();
        console.log('[CK3RAVEN] AgentViewProvider checkMcpConfiguration done');
        
        // Run paths doctor on startup (independent of MCP status)
        // Delay slightly to let extension fully activate
        setTimeout(() => {
            this.runPathsDoctor();
            console.log('[CK3RAVEN] AgentViewProvider initial runPathsDoctor triggered');
        }, 1000);
        
        // Start ongoing MCP monitoring (every 30 seconds)
        this.startMcpMonitoring();
        console.log('[CK3RAVEN] AgentViewProvider startMcpMonitoring done');
        console.log('[CK3RAVEN] AgentViewProvider constructor EXIT');
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
     * 
     * IMPORTANT: Only calls refresh() when state actually changes to prevent listener leak.
     * See: https://github.com/microsoft/vscode/issues/... (listener accumulation on frequent fire())
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
                // markMcpDisconnected updates state, so check if we need to refresh below
            } else {
                // Tools are listed - but we need to verify they're fresh
                // If tool count changed, we know VS Code just refreshed the list
                if (ck3Tools.length !== this.lastToolCount) {
                    this.toolsLastSeen = now;
                    this.lastToolCount = ck3Tools.length;
                    this.logger.info(`MCP tools refreshed: ${ck3Tools.length} tools detected`);
                    
                    // Run paths doctor when MCP tools first become available (or count changes)
                    this.runPathsDoctor();
                }

                // Dynamic provider: if tools are registered, MCP is working
                // No need to check static config file - tool presence IS the proof

                // If we haven't seen a tool count change in a while, be cautious
                // But still mark as connected if tools exist (VS Code manages the lifecycle)
                const toolsAreFresh = (now - this.toolsLastSeen) < this.TOOL_STALE_THRESHOLD_MS;
                
                if (toolsAreFresh || this.toolsLastSeen === 0) {
                    // First check or tools recently refreshed - mark as connected
                    this.toolsLastSeen = now; // Initialize on first run
                }
                
                // Update state (same for fresh or not - we trust VS Code's tool list)
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
                
                this.logger.debug(`MCP check: ${ck3Tools.length} tools, fresh=${toolsAreFresh}`);
            }
        } catch (error) {
            this.logger.error('MCP status check error:', error);
            await this.markMcpDisconnected('check error');
        }

        // CRITICAL FIX: Only refresh if state actually changed
        // This prevents listener leak from accumulating VS Code internal listeners
        const currentSignature = JSON.stringify({
            pathsDoctor: this.state.pathsDoctor,
            mcpServer: this.state.mcpServer,
            policyEnforcement: this.state.policyEnforcement
        });
        
        if (currentSignature !== this._lastStateSignature) {
            this._lastStateSignature = currentSignature;
            this.persistState();
            this.refresh();
            this.logger.debug('MCP state changed, refreshed tree view');
        }
        // else: state unchanged, skip refresh to avoid listener accumulation
    }

    /**
     * Run paths doctor CLI to check configuration health.
     * Updates pathsDoctor state with results.
     * 
     * Note: The ck3lens module is in tools/ck3lens_mcp/, so we need to set
     * PYTHONPATH to include that directory for the module to be found.
     */
    private runPathsDoctor(): void {
        const { execFile } = require('child_process');
        const os = require('os');
        const path = require('path');
        
        // Get config path for the open command
        const configPath = path.join(os.homedir(), '.ck3raven', 'config', 'workspace.toml');
        
        // Try to find Python executable in the repo .venv
        // This is best-effort - if it fails, we just mark as unchecked
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            this.state.pathsDoctor = { status: 'unchecked', errorCount: 0, warnCount: 0, configPath };
            return;
        }
        
        const workspaceRoot = workspaceFolders[0].uri.fsPath;
        const pythonPath = process.platform === 'win32'
            ? path.join(workspaceRoot, '.venv', 'Scripts', 'python.exe')
            : path.join(workspaceRoot, '.venv', 'bin', 'python');
        
        const fs = require('fs');
        if (!fs.existsSync(pythonPath)) {
            this.logger.debug('Python venv not found, paths doctor status will be unchecked');
            this.state.pathsDoctor = { status: 'unchecked', errorCount: 0, warnCount: 0, configPath };
            return;
        }
        
        // Run paths_doctor with JSON output
        // Use execFile to avoid shell quoting issues (especially with .venv paths on Windows)
        // PYTHONPATH must include tools/ck3lens_mcp where the ck3lens module lives
        const ck3lensMcpPath = path.join(workspaceRoot, 'tools', 'ck3lens_mcp');
        const env = {
            ...process.env,
            PYTHONPATH: ck3lensMcpPath + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : '')
        };
        const args = ['-m', 'ck3lens.paths_doctor', '--json'];
        
        execFile(pythonPath, args, { timeout: 10000, env }, (error: Error | null, stdout: string, stderr: string) => {
            try {
                if (error) {
                    // Log full details for debugging
                    this.logger.warn('Paths doctor failed:', error.message || '(no message)');
                    if (stderr) {
                        this.logger.debug('Paths doctor stderr:', stderr);
                    }
                    this.state.pathsDoctor = { status: 'unchecked', errorCount: 0, warnCount: 0, configPath };
                    this.refresh();
                    return;
                }
                
                const report = JSON.parse(stdout);
                const errorCount = report.summary?.ERROR || 0;
                const warnCount = report.summary?.WARN || 0;
                
                let status: PathsStatus;
                if (errorCount > 0) {
                    status = 'errors';
                } else if (warnCount > 0) {
                    status = 'warnings';
                } else {
                    status = 'healthy';
                }
                
                this.state.pathsDoctor = { 
                    status, 
                    errorCount, 
                    warnCount, 
                    configPath: report.config_path || configPath 
                };
                this.persistState();
                this.refresh();
                this.logger.info(`Paths doctor: ${status} (${errorCount} errors, ${warnCount} warnings)`);
            } catch (parseError) {
                this.logger.warn('Failed to parse paths doctor output:', parseError);
                this.state.pathsDoctor = { status: 'unchecked', errorCount: 0, warnCount: 0, configPath };
                this.refresh();
            }
        });
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
            pathsDoctor: stored?.pathsDoctor || { status: 'unchecked', errorCount: 0, warnCount: 0 },
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
            pathsDoctor: { status: 'unchecked', errorCount: 0, warnCount: 0 },
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
        console.log('[CK3RAVEN] AgentView.getChildren ENTER element=', element?.label);
        if (element) {
            console.log('[CK3RAVEN] AgentView.getChildren EXIT (has element)');
            return Promise.resolve([]);
        }

        const items: AgentTreeItem[] = [];

        // Paths Doctor status (configuration health)
        const pathsStatusLabels: Record<PathsStatus, string> = {
            healthy: 'Paths: Healthy',
            warnings: `Paths: ${this.state.pathsDoctor.warnCount} warning(s)`,
            errors: `Paths: ${this.state.pathsDoctor.errorCount} error(s)`,
            unchecked: 'Paths: Not checked'
        };
        const pathsItem = new AgentTreeItem(
            pathsStatusLabels[this.state.pathsDoctor.status],
            'paths-doctor',
            vscode.TreeItemCollapsibleState.None,
            undefined,
            'ck3lens.openPathsConfig'
        );
        const pathsIcons: Record<PathsStatus, string> = {
            healthy: 'check',
            warnings: 'warning',
            errors: 'error',
            unchecked: 'question'
        };
        const pathsColors: Record<PathsStatus, string> = {
            healthy: 'testing.iconPassed',
            warnings: 'problemsWarningIcon.foreground',
            errors: 'testing.iconFailed',
            unchecked: 'disabledForeground'
        };
        pathsItem.iconPath = new vscode.ThemeIcon(
            pathsIcons[this.state.pathsDoctor.status],
            new vscode.ThemeColor(pathsColors[this.state.pathsDoctor.status])
        );
        pathsItem.description = 'click to configure';
        pathsItem.tooltip = new vscode.MarkdownString(
            `**Paths Configuration**\n\n` +
            `Status: ${this.state.pathsDoctor.status}\n` +
            `Errors: ${this.state.pathsDoctor.errorCount}\n` +
            `Warnings: ${this.state.pathsDoctor.warnCount}\n\n` +
            `Click to open configuration file.`
        );
        items.push(pathsItem);

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

        // Instance ID display with copy action (FEAT-001)
        if (this.instanceId) {
            const instanceItem = new AgentTreeItem(
                `Instance ID: ${this.instanceId}`,
                'instance-id',
                vscode.TreeItemCollapsibleState.None,
                undefined,
                'ck3lens.agent.copyInstanceId'
            );
            instanceItem.description = 'click to copy';
            instanceItem.tooltip = new vscode.MarkdownString(
                `**MCP Server Instance ID**\n\n` +
                `ID: \`${this.instanceId}\`\n\n` +
                `Tool prefix: \`mcp_ck3_lens_${this.instanceId}_\`\n\n` +
                `Click to copy to clipboard or send to chat.`
            );
            items.push(instanceItem);
        }

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

        // FEAT-001: Copy instance ID to clipboard or send to chat
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.agent.copyInstanceId', async () => {
                if (!this.instanceId) {
                    vscode.window.showWarningMessage('Instance ID not available');
                    return;
                }

                const toolPrefix = `mcp_ck3_lens_${this.instanceId}_`;
                const actions = [
                    { label: '$(clippy) Copy Instance ID', action: 'copy_id' },
                    { label: '$(comment) Copy Tool Prefix', action: 'copy_prefix' },
                    { label: '$(comment-discussion) Send to Chat', action: 'chat' },
                ];

                const selected = await vscode.window.showQuickPick(actions, {
                    placeHolder: `Instance ID: ${this.instanceId}`,
                    title: 'Copy MCP Instance ID'
                });

                if (!selected) return;

                switch (selected.action) {
                    case 'copy_id':
                        await vscode.env.clipboard.writeText(this.instanceId);
                        vscode.window.showInformationMessage(`Copied instance ID: ${this.instanceId}`);
                        break;
                    case 'copy_prefix':
                        await vscode.env.clipboard.writeText(toolPrefix);
                        vscode.window.showInformationMessage(`Copied tool prefix: ${toolPrefix}`);
                        break;
                    case 'chat':
                        const message = `Instance: ${this.instanceId} | Tool prefix: ${toolPrefix}`;
                        await vscode.commands.executeCommand('workbench.action.chat.open', { query: message });
                        vscode.window.showInformationMessage('Instance ID sent to chat');
                        break;
                }
            })
        );

        // Open paths configuration file
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.openPathsConfig', async () => {
                const configPath = this.state.pathsDoctor.configPath;
                if (configPath) {
                    const uri = vscode.Uri.file(configPath);
                    await vscode.commands.executeCommand('vscode.open', uri);
                } else {
                    // Fall back to default location
                    const os = require('os');
                    const path = require('path');
                    const defaultPath = path.join(os.homedir(), '.ck3raven', 'config', 'workspace.toml');
                    const uri = vscode.Uri.file(defaultPath);
                    await vscode.commands.executeCommand('vscode.open', uri);
                }
            })
        );

        // Re-run paths doctor check
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.recheckPaths', () => {
                this.runPathsDoctor();
                vscode.window.showInformationMessage('Checking paths configuration...');
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
     * 
     * Sets status to 'initializing' immediately for user feedback.
     * The mode file watcher will update to actual mode when MCP confirms,
     * or the user can retry/cancel if initialization fails.
     */
    private async initializeAgentWithMode(mode: LensMode): Promise<void> {
        const modeDef = MODE_DEFINITIONS[mode];
        if (!modeDef) return;

        // Set to 'initializing' for immediate user feedback
        // Mode file watcher will update to actual mode on MCP confirmation
        this.updateAgentMode('initializing');

        this.logger.info(`Initialization requested for mode: ${mode}`);

        // Get MIT token for authorization
        const mitToken = this.getMitToken?.();

        // Open chat with initialization prompt (includes current MCP instance ID and MIT token)
        await vscode.commands.executeCommand('workbench.action.chat.open', {
            query: generateInitPrompt(mode, this.instanceId, mitToken)
        });

        vscode.window.showInformationMessage(
            `${modeDef.shortName} mode: Press Enter to send the initialization prompt`
        );
    }

    /**
     * Add a sub-agent
     * 
     * Sets status to 'initializing' for user feedback, then opens new chat.
     * The mode file watcher will update status when MCP confirms success.
     */
    private async addSubAgent(mode: LensMode): Promise<void> {
        const modeDef = MODE_DEFINITIONS[mode];
        if (!modeDef) return;

        // Set to 'initializing' for immediate user feedback
        this.updateAgentMode('initializing');

        this.logger.info(`Sub-agent initialization requested for mode: ${mode}`);

        // Get MIT token for authorization
        const mitToken = this.getMitToken?.();

        // Create new chat with initialization prompt (includes current MCP instance ID and MIT token)
        await vscode.commands.executeCommand('workbench.action.chat.newChat');
        await new Promise(resolve => setTimeout(resolve, 100));
        await vscode.commands.executeCommand('workbench.action.chat.open', {
            query: generateInitPrompt(mode, this.instanceId, mitToken)
        });

        vscode.window.showInformationMessage(
            `Sub-agent ${modeDef.shortName}: Press Enter to send the initialization prompt (new chat created)`
        );
    }

    /**
     * Set Paths Doctor status
     */
    public setPathsDoctorStatus(status: PathsStatus, errorCount: number = 0, warnCount: number = 0): void {
        this.state.pathsDoctor = { 
            ...this.state.pathsDoctor,
            status, 
            errorCount, 
            warnCount 
        };
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
