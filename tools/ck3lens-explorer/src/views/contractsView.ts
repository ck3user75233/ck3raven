/**
 * Contracts & Operations View Provider
 * 
 * Shows active contracts and rolling operation history from trace log.
 * Replaces the old RulesView with live, actionable information.
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

interface TraceEntry {
    ts: number;
    tool: string;
    args: Record<string, unknown>;
    result: Record<string, unknown>;
}

interface ContractInfo {
    id: string;
    intent?: string;
    expiresAt?: string;
    capabilities?: string[];
    allowedPaths?: string[];
}

type ContractsTreeItem = ContractItem | OperationItem | HeaderItem | InfoItem;

export class ContractsViewProvider implements vscode.TreeDataProvider<ContractsTreeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<ContractsTreeItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    
    private tracePath: string;
    private statusPath: string;
    private fileWatcher: vscode.FileSystemWatcher | undefined;
    private operations: TraceEntry[] = [];
    private activeContract: ContractInfo | null = null;
    private agentMode: string = 'none';
    // NOTE: MCP status indicator removed - agentView already shows this
    private bugReportCount: number = 0;
    
    private readonly MAX_OPERATIONS = 20; // Show last 20 operations
    
    constructor(private logger?: { info: (msg: string) => void; error: (msg: string, error?: unknown) => void }) {
        const userHome = process.env.USERPROFILE || process.env.HOME || '';
        this.tracePath = path.join(userHome, '.ck3raven', 'traces', 'ck3lens_trace.jsonl');
        this.statusPath = path.join(userHome, '.ck3raven', 'agent_status.json');
        
        // Load initial state
        this.loadTraceFile();
        this.loadAgentStatus();
        
        // Watch for trace file changes
        this.setupFileWatcher();
    }
    
    /**
     * Set up file watcher for real-time updates
     */
    private setupFileWatcher(): void {
        const traceDir = path.dirname(this.tracePath);
        
        // Create directory if it doesn't exist
        if (!fs.existsSync(traceDir)) {
            try {
                fs.mkdirSync(traceDir, { recursive: true });
            } catch (e) {
                this.logger?.error(`Failed to create trace directory: ${traceDir}`, e);
            }
        }
        
        // Watch the traces directory
        const pattern = new vscode.RelativePattern(traceDir, '*.jsonl');
        this.fileWatcher = vscode.workspace.createFileSystemWatcher(pattern);
        
        this.fileWatcher.onDidChange(() => {
            this.loadTraceFile();
            this._onDidChangeTreeData.fire(undefined);
        });
        
        // Also watch agent_status.json
        const statusDir = path.dirname(this.statusPath);
        const statusPattern = new vscode.RelativePattern(statusDir, 'agent_status.json');
        const statusWatcher = vscode.workspace.createFileSystemWatcher(statusPattern);
        
        statusWatcher.onDidChange(() => {
            this.loadAgentStatus();
            this._onDidChangeTreeData.fire(undefined);
        });
    }
    
    /**
     * Load and parse the trace file
     */
    private loadTraceFile(): void {
        try {
            if (!fs.existsSync(this.tracePath)) {
                this.operations = [];
                this.activeContract = null;
                return;
            }
            
            const content = fs.readFileSync(this.tracePath, 'utf-8');
            const lines = content.trim().split('\n').filter(l => l.trim());
            
            // Parse all lines, take last N
            const allEntries: TraceEntry[] = [];
            for (const line of lines) {
                try {
                    allEntries.push(JSON.parse(line));
                } catch (e) {
                    // Skip malformed lines
                }
            }
            
            // Get recent operations (exclude contract metadata operations from display)
            this.operations = allEntries
                .filter(e => !e.tool.includes('contract.status'))
                .slice(-this.MAX_OPERATIONS);
            
            // Find the most recent active contract
            const contractOpen = allEntries
                .filter(e => e.tool === 'ck3lens.contract.open' || e.tool === 'contract.open')
                .pop();
            
            const contractClose = allEntries
                .filter(e => e.tool === 'ck3lens.contract.close' || e.tool === 'contract.close')
                .pop();
            
            if (contractOpen) {
                const openTs = contractOpen.ts;
                const closeTs = contractClose?.ts || 0;
                
                if (openTs > closeTs) {
                    // Contract is still open
                    const result = contractOpen.result as Record<string, unknown>;
                    this.activeContract = {
                        id: (result.contract_id as string) || 'unknown',
                        intent: contractOpen.args.intent as string,
                        expiresAt: result.expires_at as string,
                        capabilities: result.capabilities as string[],
                        allowedPaths: contractOpen.args.allowed_paths as string[]
                    };
                } else {
                    this.activeContract = null;
                }
            }
            
        } catch (error) {
            this.logger?.error('Failed to load trace file', error);
            this.operations = [];
        }
    }
    
    /**
     * Load agent status from JSON file
     */
    private loadAgentStatus(): void {
        try {
            if (fs.existsSync(this.statusPath)) {
                const content = fs.readFileSync(this.statusPath, 'utf-8');
                const status = JSON.parse(content);
                this.agentMode = status.mode || 'none';
                this.bugReportCount = status.pending_bug_reports || 0;
            }
        } catch (error) {
            // Status file may not exist yet
        }
    }
    
    refresh(): void {
        this.loadTraceFile();
        this.loadAgentStatus();
        this._onDidChangeTreeData.fire(undefined);
    }
    
    getTreeItem(element: ContractsTreeItem): vscode.TreeItem {
        return element;
    }
    
    getChildren(element?: ContractsTreeItem): ContractsTreeItem[] {
        if (element) {
            return []; // No nested items
        }
        
        const items: ContractsTreeItem[] = [];
        
        // NOTE: MCP status indicator removed - agentView already shows this
        
        // Active Contract section
        items.push(new HeaderItem('Active Contract'));
        
        if (this.activeContract) {
            items.push(new ContractItem(
                this.activeContract.id,
                this.activeContract.intent || 'No intent specified',
                this.activeContract.expiresAt,
                true
            ));
        } else {
            items.push(new InfoItem('No active contract', 'Agent can still read but writes require a contract', 'info'));
        }
        
        // Bug Reports section (if any)
        if (this.bugReportCount > 0) {
            items.push(new HeaderItem('Bug Reports'));
            items.push(new InfoItem(
                `${this.bugReportCount} pending report${this.bugReportCount > 1 ? 's' : ''}`,
                'Click to view bug reports from ck3lens agents',
                'bug',
                'ck3lens.contracts.viewBugReports'
            ));
        }
        
        // Recent Operations section
        items.push(new HeaderItem('Recent Operations'));
        
        if (this.operations.length === 0) {
            items.push(new InfoItem('No operations recorded', 'Operations will appear here as the agent works', 'info'));
        } else {
            // Show operations in reverse chronological order
            const recentOps = [...this.operations].reverse().slice(0, 15);
            for (const op of recentOps) {
                items.push(new OperationItem(op));
            }
        }
        
        return items;
    }
    
    dispose(): void {
        if (this.fileWatcher) {
            this.fileWatcher.dispose();
        }
    }
}

/**
 * Header item for section labels
 */
class HeaderItem extends vscode.TreeItem {
    constructor(label: string) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.contextValue = 'header';
        // Use a subtle separator style
        this.iconPath = new vscode.ThemeIcon('dash');
        this.description = '';
    }
}

/**
 * Info item for status messages
 */
class InfoItem extends vscode.TreeItem {
    constructor(
        label: string,
        tooltip: string,
        type: 'info' | 'warning' | 'bug',
        command?: string
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);
        
        this.tooltip = tooltip;
        this.contextValue = type;
        
        switch (type) {
            case 'warning':
                this.iconPath = new vscode.ThemeIcon('warning', new vscode.ThemeColor('problemsWarningIcon.foreground'));
                break;
            case 'bug':
                this.iconPath = new vscode.ThemeIcon('bug', new vscode.ThemeColor('charts.orange'));
                break;
            default:
                this.iconPath = new vscode.ThemeIcon('info');
        }
        
        if (command) {
            this.command = {
                command,
                title: label
            };
        }
    }
}

/**
 * Contract item showing active contract details
 */
class ContractItem extends vscode.TreeItem {
    constructor(
        public readonly contractId: string,
        public readonly intent: string,
        public readonly expiresAt: string | undefined,
        public readonly isActive: boolean
    ) {
        super(contractId, vscode.TreeItemCollapsibleState.None);
        
        this.iconPath = new vscode.ThemeIcon(
            isActive ? 'file-code' : 'file',
            isActive ? new vscode.ThemeColor('testing.iconPassed') : undefined
        );
        
        this.description = intent.slice(0, 40) + (intent.length > 40 ? '...' : '');
        
        const tooltipMd = new vscode.MarkdownString();
        tooltipMd.appendMarkdown(`**Contract:** \`${contractId}\`\n\n`);
        tooltipMd.appendMarkdown(`**Intent:** ${intent}\n\n`);
        if (expiresAt) {
            tooltipMd.appendMarkdown(`**Expires:** ${expiresAt}\n\n`);
        }
        tooltipMd.appendMarkdown(`**Status:** ${isActive ? '✅ Active' : '⚫ Closed'}`);
        this.tooltip = tooltipMd;
        
        this.contextValue = 'contract';
    }
}

/**
 * Operation item showing a single trace entry
 */
class OperationItem extends vscode.TreeItem {
    constructor(public readonly entry: TraceEntry) {
        // Extract short tool name
        const toolParts = entry.tool.split('.');
        const shortName = toolParts[toolParts.length - 1];
        
        super(shortName, vscode.TreeItemCollapsibleState.None);
        
        // Determine icon based on tool type
        let icon = 'circle-outline';
        let color: vscode.ThemeColor | undefined;
        
        if (entry.tool.includes('enforcement')) {
            const decision = (entry.result as Record<string, string>).decision;
            if (decision === 'ALLOW') {
                icon = 'pass';
                color = new vscode.ThemeColor('testing.iconPassed');
            } else if (decision === 'DENY') {
                icon = 'error';
                color = new vscode.ThemeColor('testing.iconFailed');
            } else {
                icon = 'question';
                color = new vscode.ThemeColor('problemsWarningIcon.foreground');
            }
        } else if (entry.tool.includes('file')) {
            const success = (entry.result as Record<string, boolean>).success;
            icon = success ? 'file' : 'file-code';
            color = success ? new vscode.ThemeColor('testing.iconPassed') : new vscode.ThemeColor('testing.iconFailed');
        } else if (entry.tool.includes('search')) {
            icon = 'search';
        } else if (entry.tool.includes('contract')) {
            icon = 'notebook';
        } else if (entry.tool.includes('exec')) {
            icon = 'terminal';
        }
        
        this.iconPath = new vscode.ThemeIcon(icon, color);
        
        // Time description
        const date = new Date(entry.ts * 1000);
        const timeStr = date.toLocaleTimeString();
        this.description = timeStr;
        
        // Build tooltip with details
        const tooltipMd = new vscode.MarkdownString();
        tooltipMd.appendMarkdown(`**Tool:** \`${entry.tool}\`\n\n`);
        tooltipMd.appendMarkdown(`**Time:** ${date.toLocaleString()}\n\n`);
        
        // Show relevant args
        const argsToShow = { ...entry.args };
        delete argsToShow.mode; // Don't show mode, it's redundant
        if (Object.keys(argsToShow).length > 0) {
            tooltipMd.appendMarkdown(`**Args:**\n\`\`\`json\n${JSON.stringify(argsToShow, null, 2).slice(0, 500)}\n\`\`\`\n\n`);
        }
        
        // Show result summary
        if (entry.result && Object.keys(entry.result).length > 0) {
            const resultStr = JSON.stringify(entry.result, null, 2);
            if (resultStr.length > 200) {
                tooltipMd.appendMarkdown(`**Result:** (truncated)\n\`\`\`json\n${resultStr.slice(0, 200)}...\n\`\`\``);
            } else {
                tooltipMd.appendMarkdown(`**Result:**\n\`\`\`json\n${resultStr}\n\`\`\``);
            }
        }
        
        this.tooltip = tooltipMd;
        this.contextValue = 'operation';
        
        // Command to show full details
        this.command = {
            command: 'ck3lens.contracts.showOperationDetails',
            title: 'Show Details',
            arguments: [entry]
        };
    }
}
