/**
 * Issues View Provider - Unified Error/Conflict Explorer
 * 
 * Combines:
 * - Parse errors from error.log (via ck3_get_errors)
 * - Load-order conflicts from database (via ck3_list_conflict_units)
 * 
 * Features:
 * - Priority-based grouping (Critical, High, Medium, Low)
 * - One-click navigation to source
 * - "Create Patch" context menu for non-editable files
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

// Issue types
type IssueSeverity = 'critical' | 'high' | 'medium' | 'low';
type IssueKind = 'error' | 'conflict';

interface ErrorIssue {
    kind: 'error';
    severity: IssueSeverity;
    message: string;
    filePath: string | null;
    line: number | null;
    modName: string | null;
    category: string;
    fixHint: string | null;
    isCascadeRoot: boolean;
}

interface ConflictIssue {
    kind: 'conflict';
    severity: IssueSeverity;
    unitKey: string;
    domain: string;
    candidateCount: number;
    mods: string[];
    riskLevel: string;
    conflictUnitId: string;
}

type Issue = ErrorIssue | ConflictIssue;

export class IssueTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: 'severity-group' | 'error' | 'conflict' | 'info',
        public readonly issue?: Issue
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;

        // Icons based on type
        switch (itemType) {
            case 'severity-group':
                this.iconPath = new vscode.ThemeIcon('folder');
                break;
            case 'error':
                this.iconPath = new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground'));
                break;
            case 'conflict':
                this.iconPath = new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground'));
                break;
            case 'info':
                this.iconPath = new vscode.ThemeIcon('info');
                break;
        }
    }
}

export class IssuesViewProvider implements vscode.TreeDataProvider<IssueTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<IssueTreeItem | undefined | null | void> = new vscode.EventEmitter();
    readonly onDidChangeTreeData: vscode.Event<IssueTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    private issues: Issue[] = [];
    private groupedIssues: Map<IssueSeverity, Issue[]> = new Map();
    private isLoading = false;
    private lastError: string | null = null;

    // Filter state
    private severityFilter: IssueSeverity | 'all' = 'all';
    private modFilter: string | null = null;
    private showErrors = true;
    private showConflicts = true;

    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    async loadIssues(): Promise<void> {
        if (this.isLoading) {return;}
        this.isLoading = true;
        this.lastError = null;
        this.issues = [];

        try {
            // Load errors from error.log
            if (this.showErrors) {
                const errors = await this.loadErrors();
                this.issues.push(...errors);
            }

            // Load conflicts from database
            if (this.showConflicts) {
                const conflicts = await this.loadConflicts();
                this.issues.push(...conflicts);
            }

            this.groupIssuesBySeverity();
            this.refresh();

        } catch (error) {
            this.lastError = error instanceof Error ? error.message : String(error);
            this.logger.error('Failed to load issues', error);
        } finally {
            this.isLoading = false;
        }
    }

    private async loadErrors(): Promise<ErrorIssue[]> {
        if (!this.session.isInitialized) {
            return [];
        }

        try {
            const errors = await this.session.getErrors({
                priority: 4,  // Include up to medium priority
                excludeCascadeChildren: true,
                limit: 100
            });

            return errors.map(err => ({
                kind: 'error' as const,
                severity: this.priorityToSeverity(err.priority),
                message: err.message,
                filePath: err.file_path,
                line: err.game_line,
                modName: err.mod_name,
                category: err.category,
                fixHint: err.fix_hint,
                isCascadeRoot: err.is_cascading_root
            }));

        } catch (error) {
            this.logger.error('Error loading errors:', error);
            return [];
        }
    }

    private async loadConflicts(): Promise<ConflictIssue[]> {
        if (!this.session.isInitialized) {
            return [];
        }

        try {
            const conflicts = await this.session.getConflictUnits({
                limit: 50
            });

            return conflicts.map(conflict => ({
                kind: 'conflict' as const,
                severity: this.riskToSeverity(conflict.risk_level),
                unitKey: conflict.unit_key,
                domain: conflict.domain,
                candidateCount: conflict.candidate_count,
                mods: conflict.mods || [],
                riskLevel: conflict.risk_level,
                conflictUnitId: conflict.conflict_unit_id
            }));

        } catch (error) {
            this.logger.error('Error loading conflicts:', error);
            return [];
        }
    }

    private priorityToSeverity(priority: number): IssueSeverity {
        switch (priority) {
            case 1: return 'critical';
            case 2: return 'high';
            case 3: return 'medium';
            default: return 'low';
        }
    }

    private riskToSeverity(risk: string): IssueSeverity {
        switch (risk?.toLowerCase()) {
            case 'high': return 'high';
            case 'med':
            case 'medium': return 'medium';
            default: return 'low';
        }
    }

    private groupIssuesBySeverity(): void {
        this.groupedIssues.clear();
        
        // Initialize all groups
        this.groupedIssues.set('critical', []);
        this.groupedIssues.set('high', []);
        this.groupedIssues.set('medium', []);
        this.groupedIssues.set('low', []);

        for (const issue of this.issues) {
            // Apply filters
            if (this.severityFilter !== 'all' && issue.severity !== this.severityFilter) {
                continue;
            }
            if (this.modFilter) {
                const modName = issue.kind === 'error' ? issue.modName : issue.mods.join(', ');
                if (!modName?.toLowerCase().includes(this.modFilter.toLowerCase())) {
                    continue;
                }
            }

            this.groupedIssues.get(issue.severity)!.push(issue);
        }
    }

    // Filter methods
    setFilter(severity: IssueSeverity | 'all'): void {
        this.severityFilter = severity;
        this.groupIssuesBySeverity();
        this.refresh();
    }

    setModFilter(mod: string | null): void {
        this.modFilter = mod;
        this.groupIssuesBySeverity();
        this.refresh();
    }

    toggleErrors(show: boolean): void {
        this.showErrors = show;
        this.loadIssues();
    }

    toggleConflicts(show: boolean): void {
        this.showConflicts = show;
        this.loadIssues();
    }

    getTreeItem(element: IssueTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: IssueTreeItem): Promise<IssueTreeItem[]> {
        console.log('[CK3RAVEN] IssuesView.getChildren ENTER element=', element?.label);
        if (!element) {
            // Root level - show severity groups
            if (!this.session.isInitialized) {
                console.log('[CK3RAVEN] IssuesView.getChildren EXIT (not initialized)');
                return [
                    new IssueTreeItem(
                        'Initialize CK3 Lens to see issues',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    )
                ];
            }

            if (this.isLoading) {
                return [
                    new IssueTreeItem(
                        'Loading issues...',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    )
                ];
            }

            if (this.lastError) {
                return [
                    new IssueTreeItem(
                        `Error: ${this.lastError}`,
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    )
                ];
            }

            // Auto-load on first access
            if (this.issues.length === 0 && !this.lastError) {
                this.loadIssues();
                return [
                    new IssueTreeItem(
                        'Loading issues...',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    )
                ];
            }

            // Show severity groups with counts
            const items: IssueTreeItem[] = [];
            const severityLabels: Record<IssueSeverity, string> = {
                'critical': '🔴 CRITICAL',
                'high': '🟠 HIGH',
                'medium': '🟡 MEDIUM', 
                'low': '🟢 LOW'
            };
            const severityIcons: Record<IssueSeverity, vscode.ThemeIcon> = {
                'critical': new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground')),
                'high': new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground')),
                'medium': new vscode.ThemeIcon('info', new vscode.ThemeColor('list.warningForeground')),
                'low': new vscode.ThemeIcon('circle-outline')
            };

            for (const severity of ['critical', 'high', 'medium', 'low'] as IssueSeverity[]) {
                const issues = this.groupedIssues.get(severity) || [];
                if (issues.length > 0) {
                    const item = new IssueTreeItem(
                        severityLabels[severity],
                        vscode.TreeItemCollapsibleState.Collapsed,
                        'severity-group'
                    );
                    item.description = `${issues.length} issues`;
                    item.iconPath = severityIcons[severity];
                    (item as any).severity = severity;  // Store for getChildren
                    items.push(item);
                }
            }

            if (items.length === 0) {
                return [
                    new IssueTreeItem(
                        'No issues found',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    )
                ];
            }

            return items;
        }

        // Children of severity group
        if (element.itemType === 'severity-group') {
            const severity = (element as any).severity as IssueSeverity;
            const issues = this.groupedIssues.get(severity) || [];

            return issues.map(issue => {
                if (issue.kind === 'error') {
                    return this.createErrorItem(issue);
                } else {
                    return this.createConflictItem(issue);
                }
            });
        }

        return [];
    }

    private createErrorItem(error: ErrorIssue): IssueTreeItem {
        const shortPath = error.filePath ? error.filePath.split(/[/\\]/).slice(-2).join('/') : 'unknown';
        const item = new IssueTreeItem(
            error.message.substring(0, 80) + (error.message.length > 80 ? '...' : ''),
            vscode.TreeItemCollapsibleState.None,
            'error',
            error
        );
        
        item.description = error.modName ? `${error.modName} | ${shortPath}` : shortPath;
        item.tooltip = new vscode.MarkdownString(
            `**Error:** ${error.message}\n\n` +
            `**Category:** ${error.category}\n` +
            `**File:** ${error.filePath || 'unknown'}\n` +
            `**Line:** ${error.line || 'unknown'}\n` +
            `**Mod:** ${error.modName || 'unknown'}\n` +
            (error.fixHint ? `\n**Fix hint:** ${error.fixHint}` : '') +
            (error.isCascadeRoot ? '\n\n⚠️ *This is a cascade root - fixing it may resolve other errors*' : '')
        );

        // One-click navigation
        if (error.filePath) {
            item.command = {
                command: 'ck3lens.navigateToIssue',
                title: 'Navigate to Error',
                arguments: [error.filePath, error.line || 1]
            };
        }

        // Context value for "Create Patch" menu
        item.contextValue = 'error';

        return item;
    }

    private createConflictItem(conflict: ConflictIssue): IssueTreeItem {
        const item = new IssueTreeItem(
            conflict.unitKey,
            vscode.TreeItemCollapsibleState.None,
            'conflict',
            conflict
        );

        const modsShort = conflict.mods.slice(0, 3).join(', ') + (conflict.mods.length > 3 ? '...' : '');
        item.description = `${conflict.candidateCount} mods | ${conflict.domain}`;
        item.tooltip = new vscode.MarkdownString(
            `**Conflict:** ${conflict.unitKey}\n\n` +
            `**Domain:** ${conflict.domain}\n` +
            `**Risk:** ${conflict.riskLevel}\n` +
            `**Candidates:** ${conflict.candidateCount}\n` +
            `**Mods:** ${conflict.mods.join(', ')}\n\n` +
            `Click to view conflict details.`
        );

        // Command to open conflict detail
        item.command = {
            command: 'ck3lens.showConflictDetail',
            title: 'Show Conflict Detail',
            arguments: [conflict.conflictUnitId]
        };

        item.contextValue = 'conflict';

        return item;
    }
}

