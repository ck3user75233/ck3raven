/**
 * Conflicts View Provider - Show mod conflicts in tree view
 */

import * as vscode from 'vscode';
import { CK3LensSession, ConflictInfo } from '../session';
import { Logger } from '../utils/logger';

export class ConflictTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: 'conflict' | 'winner' | 'loser' | 'category',
        public readonly conflict?: ConflictInfo
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;

        switch (itemType) {
            case 'conflict':
                this.iconPath = new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground'));
                break;
            case 'winner':
                this.iconPath = new vscode.ThemeIcon('check', new vscode.ThemeColor('charts.green'));
                break;
            case 'loser':
                this.iconPath = new vscode.ThemeIcon('x', new vscode.ThemeColor('charts.red'));
                break;
            case 'category':
                this.iconPath = new vscode.ThemeIcon('folder');
                break;
        }
    }
}

export class ConflictsViewProvider implements vscode.TreeDataProvider<ConflictTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<ConflictTreeItem | undefined | null | void> = new vscode.EventEmitter();
    readonly onDidChangeTreeData: vscode.Event<ConflictTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    private conflicts: ConflictInfo[] = [];
    private groupedConflicts: Map<string, ConflictInfo[]> = new Map();

    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    showConflicts(conflicts: ConflictInfo[]): void {
        this.conflicts = conflicts;
        this.groupConflictsByFolder();
        this.refresh();
    }

    private groupConflictsByFolder(): void {
        this.groupedConflicts.clear();
        
        for (const conflict of this.conflicts) {
            const folder = conflict.folder || 'unknown';
            if (!this.groupedConflicts.has(folder)) {
                this.groupedConflicts.set(folder, []);
            }
            this.groupedConflicts.get(folder)!.push(conflict);
        }
    }

    getTreeItem(element: ConflictTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: ConflictTreeItem): Promise<ConflictTreeItem[]> {
        console.error('[CK3RAVEN] ConflictsView.getChildren ENTER element=', element?.label);
        if (!element) {
            // Root level - show folders with conflicts
            if (this.groupedConflicts.size === 0) {
                if (!this.session.isInitialized) {
                    console.error('[CK3RAVEN] ConflictsView.getChildren EXIT (not initialized)');
                    return [
                        new ConflictTreeItem(
                            'Initialize CK3 Lens to see conflicts',
                            vscode.TreeItemCollapsibleState.None,
                            'category'
                        )
                    ];
                }
                
                // Try to load conflicts
                try {
                    const conflicts = await this.session.getConflicts();
                    if (conflicts.length > 0) {
                        this.showConflicts(conflicts);
                        return this.getChildren();
                    }
                } catch (error) {
                    this.logger.error('Failed to load conflicts', error);
                }

                return [
                    new ConflictTreeItem(
                        'No conflicts detected',
                        vscode.TreeItemCollapsibleState.None,
                        'category'
                    )
                ];
            }

            const items: ConflictTreeItem[] = [];
            for (const [folder, conflicts] of this.groupedConflicts) {
                const item = new ConflictTreeItem(
                    folder,
                    vscode.TreeItemCollapsibleState.Collapsed,
                    'category'
                );
                item.description = `${conflicts.length} conflicts`;
                items.push(item);
            }
            return items;
        }

        if (element.itemType === 'category') {
            // Show conflicts in this folder
            const conflicts = this.groupedConflicts.get(element.label as string) || [];
            return conflicts.map(conflict => {
                const item = new ConflictTreeItem(
                    conflict.name,
                    vscode.TreeItemCollapsibleState.Collapsed,
                    'conflict',
                    conflict
                );
                item.description = `${conflict.winner.mod} wins`;
                item.tooltip = `${conflict.name}\nWinner: ${conflict.winner.mod}\nLosers: ${conflict.losers.map(l => l.mod).join(', ')}`;
                return item;
            });
        }

        if (element.itemType === 'conflict' && element.conflict) {
            // Show winner and losers
            const items: ConflictTreeItem[] = [];
            
            // Winner
            const winnerItem = new ConflictTreeItem(
                `✓ ${element.conflict.winner.mod}`,
                vscode.TreeItemCollapsibleState.None,
                'winner'
            );
            winnerItem.description = element.conflict.winner.file;
            winnerItem.tooltip = `Winner: ${element.conflict.winner.mod}\nFile: ${element.conflict.winner.file}\nLine: ${element.conflict.winner.line}`;
            winnerItem.command = {
                command: 'vscode.open',
                title: 'Open File',
                arguments: [
                    vscode.Uri.file(element.conflict.winner.file),
                    { selection: new vscode.Range(element.conflict.winner.line - 1, 0, element.conflict.winner.line - 1, 0) }
                ]
            };
            items.push(winnerItem);

            // Losers
            for (const loser of element.conflict.losers) {
                const loserItem = new ConflictTreeItem(
                    `✗ ${loser.mod}`,
                    vscode.TreeItemCollapsibleState.None,
                    'loser'
                );
                loserItem.description = loser.file;
                loserItem.tooltip = `Overridden: ${loser.mod}\nFile: ${loser.file}\nLine: ${loser.line}`;
                loserItem.command = {
                    command: 'vscode.open',
                    title: 'Open File',
                    arguments: [
                        vscode.Uri.file(loser.file),
                        { selection: new vscode.Range(loser.line - 1, 0, loser.line - 1, 0) }
                    ]
                };
                items.push(loserItem);
            }

            return items;
        }

        return [];
    }
}
