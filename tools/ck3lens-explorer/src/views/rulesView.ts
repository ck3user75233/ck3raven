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

export class RulesViewProvider implements vscode.TreeDataProvider<RuleItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<RuleItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    
    private configPath: string;
    private rules: RulesConfig = {};
    
    // Rule metadata for display
    private readonly ruleMetadata: { [key: string]: { displayName: string; description: string; mode: string } } = {
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
        python_validation_required: {
            displayName: 'Python Validation',
            description: 'Python code must pass syntax validation',
            mode: 'ck3raven-dev'
        },
        schema_change_declaration: {
            displayName: 'Schema Change Declaration',
            description: 'Schema changes must be classified',
            mode: 'ck3raven-dev'
        },
        preserve_uncertainty: {
            displayName: 'Preserve Uncertainty',
            description: 'Core logic must not encode gameplay assumptions',
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
    
    getTreeItem(element: RuleItem): vscode.TreeItem {
        return element;
    }
    
    getChildren(element?: RuleItem): RuleItem[] {
        if (element) {
            return []; // No nested items
        }
        
        // Build rule items from metadata
        const items: RuleItem[] = [];
        
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
     */
    enableCk3lensMode(): void {
        for (const [ruleId, meta] of Object.entries(this.ruleMetadata)) {
            if (meta.mode === 'ck3lens' || meta.mode === 'all') {
                if (!this.rules[ruleId]) {
                    this.rules[ruleId] = { enabled: true, severity: 'error' };
                } else {
                    this.rules[ruleId].enabled = true;
                }
            } else {
                // Disable rules not relevant to ck3lens mode
                if (!this.rules[ruleId]) {
                    this.rules[ruleId] = { enabled: false, severity: 'error' };
                } else {
                    this.rules[ruleId].enabled = false;
                }
            }
        }
        this.saveConfig();
        this.refresh();
        vscode.window.showInformationMessage('Enabled CK3 Lens mode rules (+ global rules)');
    }
    
    /**
     * Enable all rules for ck3raven-dev mode (includes global 'all' rules)
     */
    enableCk3ravenDevMode(): void {
        for (const [ruleId, meta] of Object.entries(this.ruleMetadata)) {
            if (meta.mode === 'ck3raven-dev' || meta.mode === 'all') {
                if (!this.rules[ruleId]) {
                    this.rules[ruleId] = { enabled: true, severity: 'error' };
                } else {
                    this.rules[ruleId].enabled = true;
                }
            } else {
                // Disable rules not relevant to ck3raven-dev mode
                if (!this.rules[ruleId]) {
                    this.rules[ruleId] = { enabled: false, severity: 'error' };
                } else {
                    this.rules[ruleId].enabled = false;
                }
            }
        }
        this.saveConfig();
        this.refresh();
        vscode.window.showInformationMessage('Enabled CK3 Raven Dev mode rules (+ global rules)');
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
        
        // Icon based on severity
        if (!enabled) {
            this.iconPath = new vscode.ThemeIcon('circle-slash', new vscode.ThemeColor('disabledForeground'));
        } else if (severity === 'error') {
            this.iconPath = new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground'));
        } else {
            this.iconPath = new vscode.ThemeIcon('warning', new vscode.ThemeColor('editorWarning.foreground'));
        }
        
        // Description shows mode and severity
        this.description = `${mode} • ${severity}`;
        
        // Tooltip with full details
        this.tooltip = new vscode.MarkdownString();
        this.tooltip.appendMarkdown(`**${displayName}**\n\n`);
        this.tooltip.appendMarkdown(`${description}\n\n`);
        this.tooltip.appendMarkdown(`- Mode: \`${mode}\`\n`);
        this.tooltip.appendMarkdown(`- Severity: \`${severity}\`\n`);
        this.tooltip.appendMarkdown(`- Status: ${enabled ? '✅ Enabled' : '❌ Disabled'}\n`);
        
        // Context value for context menu
        this.contextValue = 'rule';
    }
}
