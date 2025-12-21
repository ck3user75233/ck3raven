/**
 * CK3 Lens Widget - Agent initialization and status overlay
 * 
 * Redesigned to reflect actual agent state:
 * - MCP connection status (real Python bridge status)
 * - Agent mode (only shows mode AFTER agent confirms initialization)
 * - Active agents list with their modes
 * - Initialize/Re-initialize agent buttons that send chat commands
 */

import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

export type LensMode = 'ck3lens' | 'ck3raven-dev' | 'ck3creator' | 'none';
export type McpStatus = 'connected' | 'disconnected';

export interface AgentInstance {
    id: string;
    mode: LensMode;
    initializedAt: string;
    label: string;  // "Agent 1", "Sub-Agent 2", etc.
    isLocal?: boolean;  // True if explicitly initialized via widget button
    lastActivity?: string;  // Human-readable description of last action
    lastActivityTime?: string;  // ISO timestamp of last activity
}

export interface WidgetState {
    mcp: { status: McpStatus; latencyMs?: number; serverName?: string };
    agents: AgentInstance[];
    session: { id: string; startedAt: string };
    recentActivity?: string[];  // Last few activities for display
}

export interface WidgetConfig {
    enabled: boolean;
    anchor: 'bottomRight' | 'bottomLeft' | 'topRight' | 'topLeft';
    opacity: number;
}

/**
 * Mode definitions with behavioral contracts
 */
export const MODE_DEFINITIONS: Record<string, {
    displayName: string;
    shortName: string;
    description: string;
    icon: string;
    initPrompt: string;  // Message sent to chat to initialize agent
}> = {
    'ck3lens': {
        displayName: 'CK3 Lens',
        shortName: 'Lens',
        description: 'Full CK3 modding - conflict detection, live file editing, compatibility patches',
        icon: '$(merge)',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Lens agent by calling the ck3_get_mode_instructions tool with mode "ck3lens-live". Follow the instructions returned to complete initialization. If you cannot find the ck3_ tools, the MCP server may not be connected - check VS Code settings for MCP configuration.`
    },
    'ck3raven-dev': {
        displayName: 'CK3 Raven Dev',
        shortName: 'Raven',
        description: 'Infrastructure development - Python, MCP server, database schema',
        icon: '$(beaker)',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Raven Dev agent by calling the ck3_get_mode_instructions tool with mode "ck3raven-dev". Follow the instructions returned to complete initialization. If you cannot find the ck3_ tools, the MCP server may not be connected - check VS Code settings for MCP configuration.`
    },
    'ck3creator': {
        displayName: 'CK3 Creator',
        shortName: 'Creator',
        description: 'New content creation (events, cultures, traditions) - experimental',
        icon: '$(lightbulb)',
        initPrompt: `You have access to the ck3lens MCP server tools (prefixed with ck3_). Initialize as CK3 Creator agent by calling the ck3_get_mode_instructions tool with mode "ck3creator". Follow the instructions returned to complete initialization. If you cannot find the ck3_ tools, the MCP server may not be connected - check VS Code settings for MCP configuration.`
    }
};

export class LensWidget implements vscode.Disposable {
    private statusBarItem: vscode.StatusBarItem;
    private webviewPanel: vscode.WebviewPanel | undefined;
    private state: WidgetState;
    private config: WidgetConfig;
    private disposables: vscode.Disposable[] = [];
    private readonly stateChangeEmitter = new vscode.EventEmitter<WidgetState>();
    
    public readonly onStateChange = this.stateChangeEmitter.event;

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger
    ) {
        // Initialize state - start with NO agents (none initialized)
        this.state = this.loadState();
        this.config = this.loadConfig();

        // Create status bar item
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

        // Start periodic check for active agent sessions
        this.startAgentDetection();

        this.logger.info('Lens Widget initialized');
    }

    private loadState(): WidgetState {
        const stored = this.context.globalState.get<WidgetState>('ck3lens.widgetState');
        
        // Restore persisted state, keeping agents that were explicitly initialized
        if (stored) {
            // Keep the stored agents - they were explicitly added by the user
            return {
                mcp: stored.mcp || { status: 'disconnected' },
                agents: stored.agents || [],
                session: stored.session || { id: this.generateSessionId(), startedAt: new Date().toISOString() },
                recentActivity: stored.recentActivity || []
            };
        }
        
        // No stored state - start fresh
        return {
            mcp: { status: 'disconnected' },
            agents: [],
            session: { id: this.generateSessionId(), startedAt: new Date().toISOString() }
        };
    }

    private loadConfig(): WidgetConfig {
        const config = vscode.workspace.getConfiguration('ck3lens.widget');
        return {
            enabled: config.get<boolean>('enabled', true),
            anchor: config.get<any>('anchor', 'bottomRight'),
            opacity: config.get<number>('opacity', 0.95)
        };
    }

    /**
     * Detect active agent sessions by checking the MCP trace log.
     * If ck3_init_session or ck3_get_mode_instructions was called recently,
     * an agent is likely active.
     */
    private startAgentDetection(): void {
        // Check immediately and then periodically
        this.checkForActiveAgents();
        
        const interval = setInterval(() => {
            this.checkForActiveAgents();
        }, 30000);  // Check every 30 seconds

        this.disposables.push({ dispose: () => clearInterval(interval) });
    }

    /**
     * Convert a tool call to a human-readable activity description
     */
    private toolToActivityDescription(tool: string, args: any, result: any): string {
        // Strip prefix
        const toolName = tool.replace(/^(ck3lens\.|ck3\.)/, '');
        
        switch (toolName) {
            case 'get_mode_instructions':
                return `Initialized in ${args?.mode || 'unknown'} mode`;
            case 'init_session':
                return 'Started new session';
            case 'get_load_order':
                return 'Checked mod load order';
            case 'get_playsets':
                return 'Listed playsets';
            case 'get_conflicts':
                return `Analyzed conflicts${args?.mod_id ? ` for ${args.mod_id}` : ''}`;
            case 'get_definitions':
                return `Looked up definitions${args?.symbol ? ` for "${args.symbol}"` : ''}`;
            case 'get_references':
                return `Found references${args?.symbol ? ` for "${args.symbol}"` : ''}`;
            case 'validate_file':
                return `Validated ${args?.file_path?.split(/[/\\]/).pop() || 'file'}`;
            case 'get_file_ast':
                return `Parsed ${args?.file_path?.split(/[/\\]/).pop() || 'file'}`;
            case 'lint_mod':
                return `Linted ${args?.mod_id || 'mod'}`;
            case 'get_mod_structure':
                return `Examined mod structure`;
            case 'search_symbols':
                return `Searched for "${args?.query || 'symbols'}"`;
            case 'get_virtual_merge':
                return 'Generated virtual merge preview';
            case 'apply_merge':
                return 'Applied merge resolution';
            default:
                // Generic fallback - make the tool name readable
                return toolName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        }
    }

    private async checkForActiveAgents(): Promise<void> {
        try {
            const fs = require('fs');
            const path = require('path');
            const os = require('os');

            // Check the trace log for recent activity
            const modRoot = path.join(os.homedir(), 'Documents', 'Paradox Interactive', 'Crusader Kings III', 'mod');
            const traceFile = path.join(modRoot, 'ck3lens_trace.jsonl');

            if (!fs.existsSync(traceFile)) {
                return;
            }

            const stats = fs.statSync(traceFile);
            const lastModified = stats.mtime;
            const now = new Date();
            const ageMinutes = (now.getTime() - lastModified.getTime()) / (1000 * 60);

            // If trace file was modified in last 10 minutes, there's likely an active session
            if (ageMinutes > 10) {
                return;
            }

            // Read the last few lines to detect mode and activity
            const content = fs.readFileSync(traceFile, 'utf-8');
            const lines = content.trim().split('\n');
            const recentLines = lines.slice(-30);  // Last 30 entries for more context

            let detectedMode: LensMode = 'none';
            let lastActivity: Date | null = null;
            let lastActivityDescription = '';
            const recentActivities: string[] = [];
            let hasAnyToolActivity = false;

            for (const line of recentLines.reverse()) {
                try {
                    const entry = JSON.parse(line);
                    const entryTime = new Date(entry.ts * 1000);
                    const entryAgeMinutes = (now.getTime() - entryTime.getTime()) / (1000 * 60);

                    if (entryAgeMinutes > 10) {
                        break;  // Too old
                    }

                    const tool = entry.tool || '';
                    
                    // Skip non-tool entries
                    if (!tool.startsWith('ck3lens.') && !tool.startsWith('ck3.')) {
                        continue;
                    }

                    hasAnyToolActivity = true;

                    // Capture activity description
                    const activityDesc = this.toolToActivityDescription(tool, entry.args, entry.result);
                    
                    // First valid entry is the most recent
                    if (!lastActivity) {
                        lastActivity = entryTime;
                        lastActivityDescription = activityDesc;
                    }
                    
                    // Collect unique recent activities (up to 5)
                    if (recentActivities.length < 5 && !recentActivities.includes(activityDesc)) {
                        recentActivities.push(activityDesc);
                    }

                    // ONLY detect mode from explicit get_mode_instructions calls
                    // Do NOT default to any mode - agent must explicitly initialize
                    if ((tool === 'ck3lens.get_mode_instructions' || tool === 'ck3.get_mode_instructions') && entry.args?.mode) {
                        if (detectedMode === 'none') {
                            detectedMode = entry.args.mode as LensMode;
                        }
                    }
                    // Also check if the result explicitly contains a mode (from init_session perhaps)
                    else if (entry.result?.mode && typeof entry.result.mode === 'string' && 
                             Object.keys(MODE_DEFINITIONS).includes(entry.result.mode) && 
                             detectedMode === 'none') {
                        detectedMode = entry.result.mode as LensMode;
                    }
                    // DO NOT default to 'ck3lens' - only explicit mode initialization counts
                } catch {
                    // Skip malformed lines
                }
            }

            // Update state with recent activity
            this.state.recentActivity = recentActivities;

            // Log what we detected for debugging
            this.logger.debug(`Detection: hasActivity=${hasAnyToolActivity}, mode=${detectedMode}, activities=${recentActivities.length}`);

            // Create/update agent if there's ANY tool activity
            if (hasAnyToolActivity && lastActivity) {
                // Find existing agent or create new one
                let agent = this.state.agents.length > 0 ? this.state.agents[0] : null;
                
                if (agent) {
                    // Update existing agent's activity
                    agent.lastActivity = lastActivityDescription;
                    agent.lastActivityTime = lastActivity.toISOString();
                    // Update mode if we detected one and agent had no mode
                    if (detectedMode !== 'none' && agent.mode === 'none') {
                        agent.mode = detectedMode;
                        agent.label = 'Agent (detected)';
                    }
                } else {
                    // Create new detected agent
                    const newAgent: AgentInstance = {
                        id: this.generateAgentId(),
                        mode: detectedMode,  // Will be 'none' if not explicitly initialized
                        initializedAt: lastActivity.toISOString(),
                        label: 'Agent (detected)',
                        isLocal: false,  // Detected, not explicitly initialized
                        lastActivity: lastActivityDescription,
                        lastActivityTime: lastActivity.toISOString()
                    };
                    this.state.agents = [newAgent];
                }
                this.persistState();
                this.updateStatusBar();
                this.updateWebview();
                this.logger.debug(`Agent activity: ${lastActivityDescription}`);
            }
        } catch (error) {
            this.logger.error('Error in checkForActiveAgents:', error);
        }
    }

    /**
     * Debug helper - manually check trace file and log what we find
     */
    private async debugTraceFile(): Promise<void> {
        const fs = require('fs');
        const path = require('path');
        const os = require('os');

        const modRoot = path.join(os.homedir(), 'Documents', 'Paradox Interactive', 'Crusader Kings III', 'mod');
        const traceFile = path.join(modRoot, 'ck3lens_trace.jsonl');

        this.logger.show();  // Make sure output is visible
        this.logger.info('=== Debug Trace File ===');
        this.logger.info(`Trace file path: ${traceFile}`);

        if (!fs.existsSync(traceFile)) {
            this.logger.info('WARNING: Trace file does NOT exist!');
            vscode.window.showWarningMessage('Trace file not found. No MCP tool calls have been logged.');
            return;
        }

        const stats = fs.statSync(traceFile);
        const lastModified = stats.mtime;
        const now = new Date();
        const ageMinutes = (now.getTime() - lastModified.getTime()) / (1000 * 60);

        this.logger.info(`File exists: YES`);
        this.logger.info(`Last modified: ${lastModified.toISOString()} (${ageMinutes.toFixed(1)} minutes ago)`);
        this.logger.info(`File size: ${stats.size} bytes`);

        // Read last 10 entries
        const content = fs.readFileSync(traceFile, 'utf-8');
        const lines = content.trim().split('\n');
        this.logger.info(`Total lines: ${lines.length}`);

        this.logger.info('--- Last 10 entries ---');
        const recentLines = lines.slice(-10);
        for (const line of recentLines) {
            try {
                const entry = JSON.parse(line);
                const entryTime = new Date(entry.ts * 1000);
                const entryAgeMinutes = (now.getTime() - entryTime.getTime()) / (1000 * 60);
                this.logger.info(`  [${entryAgeMinutes.toFixed(1)}m ago] ${entry.tool} - args: ${JSON.stringify(entry.args || {}).substring(0, 100)}`);
            } catch {
                this.logger.info(`  [malformed] ${line.substring(0, 80)}...`);
            }
        }

        this.logger.info('--- Current widget state ---');
        this.logger.info(`Agents: ${JSON.stringify(this.state.agents)}`);
        this.logger.info(`MCP: ${JSON.stringify(this.state.mcp)}`);
        this.logger.info(`Recent activity: ${JSON.stringify(this.state.recentActivity)}`);
        
        vscode.window.showInformationMessage('Debug info written to CK3 Lens output channel');
    }

    private generateSessionId(): string {
        return 'S-' + Math.random().toString(36).substring(2, 10);
    }

    private generateAgentId(): string {
        return 'A-' + Math.random().toString(36).substring(2, 8);
    }

    private registerCommands(): void {
        // Initialize agent - creates agent in default mode (no specific mode yet)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.initializeAgent', async () => {
                // Create agent with 'none' mode (default mode)
                // The agent will be updated when it calls ck3_get_mode_instructions
                await this.initializeDefaultAgent();
            })
        );

        // Initialize agent with specific mode selection
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.initializeAgentWithMode', async () => {
                const items = Object.entries(MODE_DEFINITIONS).map(([id, def]) => ({
                    label: `${def.icon} ${def.displayName}`,
                    description: def.description,
                    id
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    placeHolder: 'Select agent mode to initialize',
                    title: 'Initialize Agent with Mode'
                });

                if (selected) {
                    await this.initializeAgentWithMode(selected.id as LensMode, false);
                }
            })
        );

        // Initialize sub-agent
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.initializeSubAgent', async () => {
                const items = Object.entries(MODE_DEFINITIONS).map(([id, def]) => ({
                    label: `${def.icon} ${def.displayName}`,
                    description: def.description,
                    id
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    placeHolder: 'Select sub-agent mode',
                    title: 'Initialize Sub-Agent'
                });

                if (selected) {
                    await this.initializeAgentWithMode(selected.id as LensMode, true);
                }
            })
        );

        // Re-initialize specific agent (called from webview)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.reinitializeAgent', async (agentId: string) => {
                const agent = this.state.agents.find(a => a.id === agentId);
                if (agent) {
                    if (!agent.isLocal) {
                        const confirm = await vscode.window.showWarningMessage(
                            'This agent was detected from the shared trace log and may belong to another VS Code window. Re-initializing will send a prompt to THIS window\'s chat. Continue?',
                            'Continue', 'Cancel'
                        );
                        if (confirm !== 'Continue') {
                            return;
                        }
                    }
                    await this.initializeAgentWithMode(agent.mode, agent.label.startsWith('Sub-'));
                }
            })
        );

        // Change agent mode (switch mode without full re-init prompt)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.changeAgentMode', async (agentId: string) => {
                const agent = this.state.agents.find(a => a.id === agentId);
                if (!agent) return;

                const items = Object.entries(MODE_DEFINITIONS).map(([id, def]) => ({
                    label: `${def.icon} ${def.displayName}`,
                    description: agent.mode === id ? '(current)' : def.description,
                    id,
                    picked: agent.mode === id
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    placeHolder: `Change mode for ${agent.label}`,
                    title: 'Select New Mode'
                });

                if (selected && selected.id !== agent.mode) {
                    const modeDef = MODE_DEFINITIONS[selected.id];
                    
                    // Copy mode switch prompt to clipboard
                    const switchPrompt = `Switch to ${modeDef.displayName} mode. Call the ck3_get_mode_instructions tool with mode "${selected.id}" and follow the returned instructions.`;
                    await vscode.env.clipboard.writeText(switchPrompt);
                    
                    // Update agent mode in state
                    agent.mode = selected.id as LensMode;
                    agent.initializedAt = new Date().toISOString();
                    this.persistState();
                    this.updateStatusBar();
                    this.updateWebview();
                    
                    const action = await vscode.window.showInformationMessage(
                        `Mode switch prompt copied! Paste into chat to switch to ${modeDef.shortName}.`,
                        'Open Chat'
                    );
                    
                    if (action === 'Open Chat') {
                        await vscode.commands.executeCommand('workbench.action.chat.open');
                    }
                }
            })
        );

        // Clear all agents (reset state)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.clearAgents', () => {
                this.state.agents = [];
                this.persistState();
                this.updateStatusBar();
                this.updateWebview();
                this.logger.info('All agents cleared');
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
                this.logger.show();
            })
        );

        // Copy current state
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.copyCurrentState', () => {
                const stateJson = JSON.stringify(this.state, null, 2);
                vscode.env.clipboard.writeText(stateJson);
                vscode.window.showInformationMessage('CK3 Lens state copied to clipboard');
                this.logger.info(`Widget state: ${stateJson}`);
            })
        );

        // Debug: check trace file and log findings
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.debugTrace', async () => {
                await this.debugTraceFile();
            })
        );

        // MCP reconnect
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.mcp.reconnect', async () => {
                this.setMcpStatus('disconnected');
                await vscode.commands.executeCommand('ck3lens.initSession');
            })
        );

        // Called by agent to confirm initialization (agent calls this via chat)
        this.disposables.push(
            vscode.commands.registerCommand('ck3lens.confirmAgentInit', (mode: string) => {
                this.confirmAgentInitialization(mode as LensMode);
            })
        );
    }

    /**
     * Initialize agent by opening chat with the initialization prompt
     */
    private async initializeAgentWithMode(mode: LensMode, isSubAgent: boolean): Promise<void> {
        const modeDef = MODE_DEFINITIONS[mode];
        if (!modeDef) {
            vscode.window.showErrorMessage(`Unknown mode: ${mode}`);
            return;
        }

        // Prepare the initialization prompt
        const prompt = modeDef.initPrompt;

        try {
            this.logger.info(`Initializing ${isSubAgent ? 'sub-' : ''}agent with mode: ${mode}`);
            
            // Add agent to list with session tracking BEFORE opening chat
            const agentLabel = isSubAgent 
                ? `Sub-Agent ${this.state.agents.filter(a => a.label.startsWith('Sub-')).length + 1}`
                : `Agent ${this.state.agents.filter(a => !a.label.startsWith('Sub-')).length + 1}`;
            
            const newAgent: AgentInstance = {
                id: this.generateAgentId(),
                mode: mode,
                initializedAt: new Date().toISOString(),
                label: agentLabel,
                isLocal: true  // Mark as created from THIS window
            };
            
            // Replace primary agent if not sub-agent, otherwise add
            if (!isSubAgent) {
                this.state.agents = this.state.agents.filter(a => a.label.startsWith('Sub-'));
                this.state.agents.unshift(newAgent);
            } else {
                this.state.agents.push(newAgent);
            }
            
            this.persistState();
            this.updateStatusBar();
            this.updateWebview();

            if (isSubAgent) {
                // For sub-agents: Create a NEW chat session with the prompt pre-filled
                // First create a new chat, then open it with the query
                await vscode.commands.executeCommand('workbench.action.chat.newChat');
                // Small delay to ensure new chat is ready
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            
            // Open chat with the initialization prompt pre-filled in the input
            // The 'query' parameter pre-fills the chat input box
            await vscode.commands.executeCommand('workbench.action.chat.open', {
                query: prompt
            });
            
            // Also copy to clipboard as backup
            await vscode.env.clipboard.writeText(prompt);
            
            // Show brief notification
            vscode.window.showInformationMessage(
                `${modeDef.shortName} mode: Press Enter to send the initialization prompt${isSubAgent ? ' (new chat created)' : ''}`
            );
            
        } catch (error) {
            this.logger.error('Failed to initialize agent', error);
            vscode.window.showErrorMessage(`Failed to initialize agent: ${error}`);
        }
    }

    /**
     * Initialize agent in default mode (no specific mode)
     * This just marks that an agent is now active in the chat
     */
    private async initializeDefaultAgent(): Promise<void> {
        // Create agent with 'none' mode - will be updated when agent calls get_mode_instructions
        const newAgent: AgentInstance = {
            id: this.generateAgentId(),
            mode: 'none',
            initializedAt: new Date().toISOString(),
            label: 'Agent',
            isLocal: true
        };
        
        // Replace any existing primary agent
        this.state.agents = this.state.agents.filter(a => a.label.startsWith('Sub-'));
        this.state.agents.unshift(newAgent);
        
        this.persistState();
        this.updateStatusBar();
        this.updateWebview();
        
        this.logger.info('Agent initialized in default mode');
        vscode.window.showInformationMessage('Agent marked as active. Use Re-init to set a specific mode.');
    }

    /**
     * Called by agent to confirm it has initialized into a mode
     */
    public confirmAgentInitialization(mode: LensMode): void {
        const primaryAgent = this.state.agents.find(a => !a.label.startsWith('Sub-'));
        if (primaryAgent) {
            primaryAgent.mode = mode;
            primaryAgent.initializedAt = new Date().toISOString();
        } else {
            this.state.agents.unshift({
                id: this.generateAgentId(),
                mode: mode,
                initializedAt: new Date().toISOString(),
                label: 'Agent 1'
            });
        }
        
        this.persistState();
        this.updateStatusBar();
        this.updateWebview();
        this.stateChangeEmitter.fire(this.state);
        
        const modeDef = MODE_DEFINITIONS[mode];
        this.logger.info(`Agent confirmed initialization as: ${mode}`);
        vscode.window.showInformationMessage(`Agent initialized as ${modeDef?.displayName || mode}`);
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
    public getState(): WidgetState {
        return { ...this.state };
    }

    /**
     * Get primary agent mode (for compatibility)
     */
    public getPrimaryAgentMode(): LensMode {
        const primary = this.state.agents.find(a => !a.label.startsWith('Sub-'));
        return primary?.mode || 'none';
    }

    // Legacy methods for compatibility - no-ops now
    public setLensEnabled(_enabled: boolean): void {}
    public setAgentStatus(_status: string, _error?: string): void {}
    public setMode(_mode: string): void {}

    private persistState(): void {
        this.context.globalState.update('ck3lens.widgetState', this.state);
    }

    private updateStatusBar(): void {
        const mcpIcon = this.state.mcp.status === 'connected' ? '$(database)' : '$(circle-slash)';
        const primaryAgent = this.state.agents.find(a => !a.label.startsWith('Sub-'));
        const modeDef = primaryAgent ? MODE_DEFINITIONS[primaryAgent.mode] : null;
        
        let text: string;
        if (!primaryAgent || primaryAgent.mode === 'none') {
            text = `${mcpIcon} CK3 Lens`;
        } else {
            text = `${mcpIcon} ${modeDef?.shortName || primaryAgent.mode}`;
        }
        
        if (this.state.agents.length > 1) {
            text += ` (${this.state.agents.length})`;
        }

        this.statusBarItem.text = text;
        this.statusBarItem.tooltip = new vscode.MarkdownString(
            `**CK3 Lens**\n\n` +
            `- MCP: ${this.state.mcp.status}${this.state.mcp.latencyMs ? ` (${this.state.mcp.latencyMs}ms)` : ''}\n` +
            `- Agents: ${this.state.agents.length === 0 ? 'None initialized' : this.state.agents.map(a => `${a.label}: ${a.mode}`).join(', ')}\n\n` +
            `Click to open widget panel`
        );

        if (this.state.mcp.status === 'disconnected') {
            this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
        } else if (this.state.agents.length > 0) {
            this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.activeBackground');
        } else {
            this.statusBarItem.backgroundColor = undefined;
        }
    }

    private showWebviewPanel(): void {
        if (this.webviewPanel) {
            this.webviewPanel.reveal();
            this.updateWebview();  // Refresh HTML when revealing existing panel
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
            (message: { command: string; [key: string]: any }) => this.handleWebviewMessage(message),
            null,
            this.disposables
        );

        this.updateWebview();
    }

    private handleWebviewMessage(message: any): void {
        switch (message.command) {
            case 'initializeAgent':
                vscode.commands.executeCommand('ck3lens.initializeAgent');
                break;
            case 'initializeSubAgent':
                vscode.commands.executeCommand('ck3lens.initializeSubAgent');
                break;
            case 'reinitializeAgent':
                vscode.commands.executeCommand('ck3lens.reinitializeAgent', message.agentId);
                break;
            case 'changeAgentMode':
                vscode.commands.executeCommand('ck3lens.changeAgentMode', message.agentId);
                break;
            case 'clearAgents':
                vscode.commands.executeCommand('ck3lens.clearAgents');
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
            case 'setupPlayset':
                vscode.commands.executeCommand('ck3lens.setupPlayset');
                break;
            case 'viewPlaysets':
                vscode.commands.executeCommand('ck3lens.viewPlaysets');
                break;
            case 'debugTrace':
                vscode.commands.executeCommand('ck3lens.debugTrace');
                break;
        }
    }

    private updateWebview(): void {
        if (!this.webviewPanel) return;
        this.webviewPanel.webview.html = this.getWebviewHtml();
    }

    private getWebviewHtml(): string {
        const nonce = this.getNonce();
        
        // Helper to format relative time
        const formatRelativeTime = (isoTime: string | undefined): string => {
            if (!isoTime) return '';
            const diff = Date.now() - new Date(isoTime).getTime();
            const mins = Math.floor(diff / 60000);
            if (mins < 1) return 'just now';
            if (mins < 60) return `${mins}m ago`;
            const hours = Math.floor(mins / 60);
            if (hours < 24) return `${hours}h ago`;
            return `${Math.floor(hours / 24)}d ago`;
        };

        const agentsHtml = this.state.agents.length === 0
            ? ''  // No agents - will show Initialize button instead
            : this.state.agents.map(agent => {
                const modeDef = MODE_DEFINITIONS[agent.mode];
                const activityTime = formatRelativeTime(agent.lastActivityTime);
                
                // Build activity list - show recent activities or a placeholder
                let activityHtml = '';
                if (agent.lastActivity) {
                    activityHtml = `
                        <div class="agent-activity">
                            <span class="activity-text">${agent.lastActivity}</span>
                            ${activityTime ? `<span class="activity-time">${activityTime}</span>` : ''}
                        </div>`;
                }
                
                // Show recent activities from state if available
                const recentActivitiesHtml = this.state.recentActivity && this.state.recentActivity.length > 0
                    ? this.state.recentActivity.slice(0, 3).map(activity => 
                        `<div class="activity-item">• ${activity}</div>`
                    ).join('')
                    : '';
                
                // Display: "Agent - initialized by VS Code" or "Agent - ck3lens" etc.
                const modeLabel = agent.mode === 'none' 
                    ? 'initialized by VS Code'
                    : (modeDef?.shortName || agent.mode);

                return `
                    <div class="agent-row">
                        <div class="agent-info">
                            <div class="agent-header">
                                <span class="agent-label">Agent - ${modeLabel}</span>
                                <button class="btn-reinit" data-agent-id="${agent.id}" data-action="reinit" title="Re-initialize to a specific mode">Re-init</button>
                            </div>
                            ${activityHtml}
                            ${recentActivitiesHtml ? `<div class="recent-activities">${recentActivitiesHtml}</div>` : ''}
                        </div>
                    </div>
                `;
            }).join('');

        // Build action buttons based on state
        const hasAgents = this.state.agents.length > 0;
        const actionButtonsHtml = hasAgents 
            ? `<button class="btn-secondary full-width" id="addSubAgent">+ Add Sub-agent</button>`
            : `<button class="btn-primary full-width" id="initAgent">Initialize Agent</button>`;
        
        const clearButtonHtml = hasAgents
            ? `<button class="btn-ghost full-width" id="clearAgents">Clear All Agents</button>`
            : '';

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
            min-width: 300px;
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
        .status-indicator.connected { background: #4caf50; }
        .status-indicator.disconnected { background: #f44336; }
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
        .btn-small {
            width: auto;
            padding: 4px 8px;
            font-size: 11px;
            margin: 0;
        }
        .btn-mode {
            width: auto;
            padding: 2px 6px;
            font-size: 10px;
            margin: 0;
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        .agent-row {
            padding: 10px;
            margin: 4px 0;
            background: var(--vscode-editor-background);
            border-radius: 4px;
            border: 1px solid var(--vscode-panel-border);
            border-left: 3px solid var(--vscode-activityBarBadge-background);
        }
        .agent-info {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .agent-header {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .agent-label {
            font-weight: bold;
            font-size: 13px;
        }
        .mode-badge {
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 3px;
            background: var(--vscode-activityBarBadge-background);
            color: var(--vscode-activityBarBadge-foreground);
        }
        .mode-badge.uninitialized {
            background: var(--vscode-editorWarning-foreground);
            color: var(--vscode-editor-background);
        }
        .no-agents {
            text-align: center;
            color: var(--vscode-descriptionForeground);
            font-style: italic;
            padding: 12px;
        }
        .no-agents .hint {
            font-size: 10px;
            opacity: 0.8;
        }
        .activity-list {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
        }
        .activity-item {
            padding: 2px 0;
            border-bottom: 1px solid var(--vscode-panel-border);
        }
        .activity-item:last-child {
            border-bottom: none;
        }
        .agent-subtitle {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin-bottom: 4px;
        }
        .agent-activity {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 4px 8px;
            background: var(--vscode-textBlockQuote-background);
            border-radius: 3px;
            font-size: 11px;
            margin-top: 4px;
        }
        .activity-text {
            color: var(--vscode-foreground);
            flex: 1;
        }
        .activity-time {
            color: var(--vscode-descriptionForeground);
            font-size: 10px;
        }
        .recent-activities {
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px solid var(--vscode-panel-border);
        }
        .recent-activities .activity-item {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            padding: 2px 0;
        }
        .btn-reinit {
            width: auto;
            padding: 2px 8px;
            font-size: 10px;
            margin: 0;
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        .btn-primary {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
        }
        .btn-secondary {
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        .btn-ghost {
            background: transparent;
            color: var(--vscode-descriptionForeground);
            border: 1px solid var(--vscode-panel-border);
        }
        .full-width {
            width: 100%;
        }
        .quick-actions {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px;
        }
        .quick-actions button {
            font-size: 12px;
            padding: 6px 8px;
        }
        .health {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            text-align: center;
            margin-top: 12px;
        }
    </style>
</head>
<body>
    <div class="section">
        <div class="section-title">MCP Connection</div>
        <div class="status-row">
            <span class="status-indicator ${this.state.mcp.status}"></span>
            <span>MCP: ${this.state.mcp.status}</span>
            ${this.state.mcp.latencyMs ? `<span style="color: var(--vscode-descriptionForeground)">(${this.state.mcp.latencyMs}ms)</span>` : ''}
        </div>
        ${this.state.mcp.serverName ? `<div style="font-size: 11px; color: var(--vscode-descriptionForeground)">Server: ${this.state.mcp.serverName}</div>` : ''}
        ${this.state.mcp.status === 'disconnected' ? '<button class="btn-secondary" id="btn-reconnect">Reconnect</button>' : ''}
    </div>

    <div class="section">
        <div class="section-title">${this.state.agents.length > 0 ? 'Agent Mode' : 'Agents'}</div>
        ${agentsHtml}
        ${actionButtonsHtml}
        ${clearButtonHtml}
    </div>

    <div class="section">
        <div class="section-title">Quick Actions</div>
        <div class="quick-actions">
            <button class="btn-secondary" id="btn-logs">📋 Logs</button>
            <button class="btn-secondary" id="btn-state">📋 State</button>
            <button class="btn-secondary" id="btn-settings">⚙️ Settings</button>
        </div>
        <button class="btn-ghost full-width" id="btn-debug" style="margin-top: 8px; font-size: 10px;">🔍 Debug Trace</button>
    </div>

    <div class="health">
        Session: ${this.state.session.id}
    </div>

    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        
        // Add event listeners when DOM is ready
        document.addEventListener('DOMContentLoaded', function() {
            // Initialize Agent button
            const initBtn = document.getElementById('initAgent');
            if (initBtn) {
                initBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'initializeAgent' });
                });
            }
            
            // Reconnect MCP button
            const reconnectBtn = document.getElementById('btn-reconnect');
            if (reconnectBtn) {
                reconnectBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'reconnectMcp' });
                });
            }
            
            // Quick action buttons
            const logsBtn = document.getElementById('btn-logs');
            if (logsBtn) {
                logsBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'openLogs' });
                });
            }
            
            const stateBtn = document.getElementById('btn-state');
            if (stateBtn) {
                stateBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'copyState' });
                });
            }
            
            const settingsBtn = document.getElementById('btn-settings');
            if (settingsBtn) {
                settingsBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'openSettings' });
                });
            }
            
            // Agent re-init buttons (data-action="reinit")
            document.querySelectorAll('[data-action="reinit"]').forEach(function(btn) {
                btn.addEventListener('click', function() {
                    const agentId = btn.getAttribute('data-agent-id');
                    vscode.postMessage({ command: 'reinitializeAgent', agentId: agentId });
                });
            });
            
            // Add Sub-agent button
            const addSubagentBtn = document.getElementById('addSubAgent');
            if (addSubagentBtn) {
                addSubagentBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'initializeSubAgent' });
                });
            }
            
            // Clear all agents button
            const clearAgentsBtn = document.getElementById('clearAgents');
            if (clearAgentsBtn) {
                clearAgentsBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'clearAgents' });
                });
            }
            
            // Debug trace button
            const debugBtn = document.getElementById('btn-debug');
            if (debugBtn) {
                debugBtn.addEventListener('click', function() {
                    vscode.postMessage({ command: 'debugTrace' });
                });
            }
        });
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
