/**
 * Validation Rules View Provider
 * 
 * Shows policy validation rules with toggles to enable/disable each rule.
 * Reads configuration from ck3lens_config.yaml.
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'js-yaml';

interface RuleConfig {
    enabled: boolean;
    severity: string;
}

interface RulesConfig {
    [ruleName: string]: RuleConfig;
}

export class RulesViewProvider implements vscode.TreeDataProvider<RuleItem | WarningItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<RuleItem | WarningItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    
    // Support checkbox state changes
    readonly onDidChangeCheckboxState = new vscode.EventEmitter<vscode.TreeCheckboxChangeEvent<RuleItem>>();
    
    private configPath: string;
    private rules: RulesConfig = {};
    private treeView: vscode.TreeView<RuleItem | WarningItem> | undefined;
    private mcpConnected: boolean = false;
    private mcpCheckInterval: NodeJS.Timeout | undefined;
    
    // Rule metadata for display
    private readonly ruleMetadata: { [key: string]: { displayName: string; description: string; mode: string } } = {
        // === GLOBAL RULES (all modes) ===
        tool_trace_required: {
            displayName: 'Tool Trace Required',
            description: 'All conclusions must be derivable from MCP tool traces',
            mode: 'all'
        },
        no_silent_assumptions: {
            displayName: 'No Silent Assumptions',
            description: 'Agent may not guess without tool evidence',
            mode: 'all'
        },
        
        // === CK3 LENS RULES ===
        active_playset_enforcement: {
            displayName: 'Active Playset Scope',
            description: 'Searches limited to active playset',
            mode: 'ck3lens'
        },
        database_first_search: {
            displayName: 'Database-First Search',
            description: 'DB search before filesystem access',
            mode: 'ck3lens'
        },
        ck3_file_model_required: {
            displayName: 'CK3 File Model Required',
            description: 'Every CK3 file must declare A/B/C/D model',
            mode: 'ck3lens'
        },
        file_path_domain_validation: {
            displayName: 'File Path Validation',
            description: 'Paths must match CK3 domain semantics',
            mode: 'ck3lens'
        },
        new_symbol_declaration: {
            displayName: 'New Symbol Declaration',
            description: 'New symbols must be declared and justified',
            mode: 'ck3lens'
        },
        symbol_resolution: {
            displayName: 'Symbol Resolution',
            description: 'All symbols must resolve against known sources',
            mode: 'ck3lens'
        },
        conflict_alignment: {
            displayName: 'Conflict Alignment',
            description: 'Modified units must correspond to resolved conflicts',
            mode: 'ck3lens'
        },
        negative_claims: {
            displayName: 'Negative Claims Proof',
            description: 'Non-existence claims require ck3_confirm_not_exists',
            mode: 'ck3lens'
        },
        
        // === CK3 RAVEN DEV RULES ===
        allowed_python_paths: {
            displayName: 'Allowed Python Paths',
            description: 'New .py files must be in src/, tests/, scripts/, examples/, tools/, or builder/',
            mode: 'ck3raven-dev'
        },
        scripts_must_be_documented: {
            displayName: 'Scripts Must Be Documented',
            description: 'Scripts in scripts/ must have entry in scripts/README.md',
            mode: 'ck3raven-dev'
        },
        ephemeral_scripts_location: {
            displayName: 'Ephemeral Scripts Location',
            description: 'scratch_*, tmp_*, workaround_* files must go to .artifacts/ (never committed)',
            mode: 'ck3raven-dev'
        },
        bugfix_requires_core_change: {
            displayName: 'Bugfix Requires Core Change',
            description: 'Bugfixes must modify core code in src/, not just create scripts',
            mode: 'ck3raven-dev'
        },
        bugfix_requires_test: {
            displayName: 'Bugfix Requires Test',
            description: 'Bugfixes must include a regression test under tests/',
            mode: 'ck3raven-dev'
        },
        architecture_intent_required: {
            displayName: 'Architecture Intent',
            description: 'Declare intent (bugfix/feature/refactor) and output_kind (core_change/maintenance_script/experiment)',
            mode: 'ck3raven-dev'
        },
        python_validation_required: {
            displayName: 'Python Validation',
            description: 'Python code must pass syntax validation',
            mode: 'ck3raven-dev'
        },
        schema_change_declaration: {
            displayName: 'Schema Change Declaration',
            description: 'Schema changes must be classified as breaking/non-breaking',
            mode: 'ck3raven-dev'
        },
        preserve_uncertainty: {
            displayName: 'Preserve Uncertainty',
            description: 'Parser/DB must not encode gameplay assumptions - store data as-is',
            mode: 'ck3raven-dev'
        }
    };
    
    constructor(private logger?: { info: (msg: string) => void; error: (msg: string, error?: unknown) => void }) {
        // Look for config in AI Workspace
        const aiWorkspace = path.join(
            process.env.USERPROFILE || process.env.HOME || '',
            'Documents', 'AI Workspace'
        );
        this.configPath = path.join(aiWorkspace, 'ck3lens_config.yaml');
        this.loadConfig();
        
        // Check MCP status immediately and periodically
        this.checkMcpStatus();
        this.mcpCheckInterval = setInterval(() => this.checkMcpStatus(), 15000); // Every 15 seconds
    }
    
    /**
     * Check if MCP server tools are available
     */
    private checkMcpStatus(): void {
        try {
            const allTools = vscode.lm.tools;
            const ck3Tools = allTools.filter(tool => tool.name.startsWith('mcp_ck3lens_ck3_'));
            const wasConnected = this.mcpConnected;
            this.mcpConnected = ck3Tools.length > 0;
            
            // Refresh if status changed
            if (wasConnected !== this.mcpConnected) {
                this.logger?.info(`MCP status changed: ${this.mcpConnected ? 'connected' : 'disconnected'}`);
                this._onDidChangeTreeData.fire(undefined);
            }
        } catch (error) {
            if (this.mcpConnected) {
                this.mcpConnected = false;
                this._onDidChangeTreeData.fire(undefined);
            }
        }
    }
    
    /**
     * Clean up interval on dispose
     */
    dispose(): void {
        if (this.mcpCheckInterval) {
            clearInterval(this.mcpCheckInterval);
        }
    }
    
    /**
     * Register tree view to handle checkbox changes
     */
    registerTreeView(treeView: vscode.TreeView<RuleItem | WarningItem>): void {
        this.treeView = treeView;
        treeView.onDidChangeCheckboxState(async (e) => {
            for (const [item, state] of e.items) {
                // Only process RuleItem, not WarningItem
                if (item instanceof RuleItem) {
                    const enabled = state === vscode.TreeItemCheckboxState.Checked;
                    if (!this.rules[item.ruleId]) {
                        this.rules[item.ruleId] = { enabled, severity: 'error' };
                    } else {
                        this.rules[item.ruleId].enabled = enabled;
                    }
                }
            }
            this.saveConfig();
            this.refresh();
        });
    }
    
    private loadConfig(): void {
        try {
            if (fs.existsSync(this.configPath)) {
                const content = fs.readFileSync(this.configPath, 'utf-8');
                const config = yaml.load(content) as any;
                this.rules = config?.validation_rules || {};
            }
        } catch (error) {
            console.error('Failed to load rules config:', error);
            this.rules = {};
        }
    }
    
    private saveConfig(): void {
        try {
            let config: any = {};
            
            // Load existing config
            if (fs.existsSync(this.configPath)) {
                const content = fs.readFileSync(this.configPath, 'utf-8');
                config = yaml.load(content) as any || {};
            }
            
            // Update validation_rules section
            config.validation_rules = this.rules;
            
            // Write back
            const yamlStr = yaml.dump(config, { indent: 2, lineWidth: 120 });
            fs.writeFileSync(this.configPath, yamlStr, 'utf-8');
        } catch (error) {
            vscode.window.showErrorMessage(`Failed to save rules config: ${error}`);
        }
    }
    
    refresh(): void {
        this.loadConfig();
        this._onDidChangeTreeData.fire(undefined);
    }
    
    getTreeItem(element: RuleItem | WarningItem): vscode.TreeItem {
        return element;
    }
    
    getChildren(element?: RuleItem | WarningItem): (RuleItem | WarningItem)[] {
        if (element) {
            return []; // No nested items
        }
        
        const items: (RuleItem | WarningItem)[] = [];
        
        // Show warning if MCP is not connected
        if (!this.mcpConnected) {
            items.push(new WarningItem(
                '⚠️ MCP Server Offline',
                'Policy rules are NOT being enforced! The agent can bypass all rules below.',
                'Start the MCP server to enable policy enforcement.'
            ));
        }
        
        // Build rule items from metadata
        for (const [ruleId, meta] of Object.entries(this.ruleMetadata)) {
            const config = this.rules[ruleId] || { enabled: true, severity: 'error' };
            items.push(new RuleItem(
                ruleId,
                meta.displayName,
                meta.description,
                meta.mode,
                config.enabled,
                config.severity
            ));
        }
        
        return items;
    }
    
    async toggleRule(ruleId: string): Promise<void> {
        if (!this.rules[ruleId]) {
            this.rules[ruleId] = { enabled: true, severity: 'error' };
        }
        
        this.rules[ruleId].enabled = !this.rules[ruleId].enabled;
        this.saveConfig();
        this.refresh();
        
        const status = this.rules[ruleId].enabled ? 'enabled' : 'disabled';
        vscode.window.showInformationMessage(`Rule "${ruleId}" ${status}`);
    }
    
    async setSeverity(ruleId: string): Promise<void> {
        const severity = await vscode.window.showQuickPick(
            ['error', 'warning'],
            { placeHolder: 'Select severity level' }
        );
        
        if (severity) {
            if (!this.rules[ruleId]) {
                this.rules[ruleId] = { enabled: true, severity: 'error' };
            }
            this.rules[ruleId].severity = severity;
            this.saveConfig();
            this.refresh();
        }
    }
    
    /**
     * Enable all rules for ck3lens mode (includes global 'all' rules)
     * Resets all rules to default state (enabled with error severity for relevant rules)
     */
    enableCk3lensMode(): void {
        for (const [ruleId, meta] of Object.entries(this.ruleMetadata)) {
            if (meta.mode === 'ck3lens' || meta.mode === 'all') {
                // Enable and reset to default severity
                this.rules[ruleId] = { enabled: true, severity: 'error' };
            } else {
                // Disable rules not relevant to ck3lens mode
                this.rules[ruleId] = { enabled: false, severity: 'error' };
            }
        }
        this.saveConfig();
        this.refresh();
        vscode.window.showInformationMessage('Reset to CK3 Lens mode defaults');
    }
    
    /**
     * Enable all rules for ck3raven-dev mode (includes global 'all' rules)
     * Resets all rules to default state (enabled with error severity for relevant rules)
     */
    enableCk3ravenDevMode(): void {
        for (const [ruleId, meta] of Object.entries(this.ruleMetadata)) {
            if (meta.mode === 'ck3raven-dev' || meta.mode === 'all') {
                // Enable and reset to default severity
                this.rules[ruleId] = { enabled: true, severity: 'error' };
            } else {
                // Disable rules not relevant to ck3raven-dev mode
                this.rules[ruleId] = { enabled: false, severity: 'error' };
            }
        }
        this.saveConfig();
        this.refresh();
        vscode.window.showInformationMessage('Reset to CK3 Raven Dev mode defaults');
    }
    
    /**
     * Disable all rules
     */
    disableAllRules(): void {
        for (const ruleId of Object.keys(this.ruleMetadata)) {
            if (!this.rules[ruleId]) {
                this.rules[ruleId] = { enabled: false, severity: 'error' };
            } else {
                this.rules[ruleId].enabled = false;
            }
        }
        this.saveConfig();
        this.refresh();
        vscode.window.showInformationMessage('Disabled all validation rules');
    }
    
    /**
     * Get the path to the config file for opening in editor
     */
    getConfigPath(): string | undefined {
        if (fs.existsSync(this.configPath)) {
            return this.configPath;
        }
        return undefined;
    }
}

/**
 * Warning item shown when policies are not being enforced
 */
class WarningItem extends vscode.TreeItem {
    constructor(
        label: string,
        private readonly warningMessage: string,
        private readonly actionHint: string
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);
        
        this.iconPath = new vscode.ThemeIcon('warning', new vscode.ThemeColor('problemsWarningIcon.foreground'));
        this.description = 'rules not enforced';
        
        this.tooltip = new vscode.MarkdownString();
        this.tooltip.appendMarkdown(`**⚠️ Policy Enforcement Inactive**\n\n`);
        this.tooltip.appendMarkdown(`${this.warningMessage}\n\n`);
        this.tooltip.appendMarkdown(`---\n\n`);
        this.tooltip.appendMarkdown(`**Action:** ${this.actionHint}`);
        
        this.contextValue = 'warning';
    }
}

class RuleItem extends vscode.TreeItem {
    constructor(
        public readonly ruleId: string,
        public readonly displayName: string,
        public readonly description: string,
        public readonly mode: string,
        public readonly enabled: boolean,
        public readonly severity: string
    ) {
        super(displayName, vscode.TreeItemCollapsibleState.None);
        
        // Set checkbox state
        this.checkboxState = enabled 
            ? vscode.TreeItemCheckboxState.Checked 
            : vscode.TreeItemCheckboxState.Unchecked;
        
        // Icon based on enabled state (green check = enabled, gray slash = disabled)
        if (!enabled) {
            this.iconPath = new vscode.ThemeIcon('circle-slash', new vscode.ThemeColor('disabledForeground'));
        } else {
            this.iconPath = new vscode.ThemeIcon('check', new vscode.ThemeColor('testing.iconPassed'));
        }
        
        // Description with colored severity indicator
        const modeIndicator = mode === 'all' ? '⭐' : mode === 'ck3lens' ? '🔷' : '🔶';
        if (enabled) {
            const severityIndicator = severity === 'error' ? '🔴' : '🟡';
            this.description = `${modeIndicator} ${severityIndicator}`;
        } else {
            this.description = `${modeIndicator} ⚫`;
        }
        
        // Tooltip with full details and instructions
        this.tooltip = new vscode.MarkdownString();
        this.tooltip.appendMarkdown(`**${displayName}**\n\n`);
        this.tooltip.appendMarkdown(`${description}\n\n`);
        this.tooltip.appendMarkdown(`---\n\n`);
        this.tooltip.appendMarkdown(`**Mode:** ${mode === 'all' ? '⭐ Global' : mode === 'ck3lens' ? '🔷 CK3 Lens' : '🔶 CK3 Raven Dev'}\n\n`);
        this.tooltip.appendMarkdown(`**Severity:** ${severity === 'error' ? '🔴 Error' : '🟡 Warning'}\n\n`);
        this.tooltip.appendMarkdown(`**Status:** ${enabled ? '✅ Enabled' : '⚫ Disabled'}\n\n`);
        this.tooltip.appendMarkdown(`---\n\n`);
        this.tooltip.appendMarkdown(`*Right-click to change severity*`);
        
        // Context value for context menu
        this.contextValue = 'rule';
    }
}
