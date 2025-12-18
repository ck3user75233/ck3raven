/**
 * Live Mods View Provider - Show editable mods with git status
 */

import * as vscode from 'vscode';
import { CK3LensSession, LiveModInfo } from '../session';
import { Logger } from '../utils/logger';

export class LiveModTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: 'mod' | 'file' | 'category',
        public readonly mod?: LiveModInfo,
        public readonly data?: any
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;

        switch (itemType) {
            case 'mod':
                this.iconPath = new vscode.ThemeIcon('package');
                break;
            case 'file':
                this.iconPath = new vscode.ThemeIcon('file');
                break;
            case 'category':
                this.iconPath = new vscode.ThemeIcon('folder');
                break;
        }
    }
}

export class LiveModsViewProvider implements vscode.TreeDataProvider<LiveModTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<LiveModTreeItem | undefined | null | void> = new vscode.EventEmitter();
    readonly onDidChangeTreeData: vscode.Event<LiveModTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    private liveMods: LiveModInfo[] = [];

    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: LiveModTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: LiveModTreeItem): Promise<LiveModTreeItem[]> {
        if (!element) {
            // Root level - show live mods
            if (!this.session.isInitialized) {
                return [
                    new LiveModTreeItem(
                        'Initialize CK3 Lens to see live mods',
                        vscode.TreeItemCollapsibleState.None,
                        'category'
                    )
                ];
            }

            try {
                this.liveMods = await this.session.getLiveMods();
                
                if (this.liveMods.length === 0) {
                    return [
                        new LiveModTreeItem(
                            'No live mods configured',
                            vscode.TreeItemCollapsibleState.None,
                            'category'
                        )
                    ];
                }

                return this.liveMods.map(mod => {
                    const item = new LiveModTreeItem(
                        mod.name,
                        vscode.TreeItemCollapsibleState.Collapsed,
                        'mod',
                        mod
                    );
                    item.description = mod.exists ? mod.modId : '(not found)';
                    item.tooltip = new vscode.MarkdownString(
                        `**${mod.name}**\n\n` +
                        `- **ID:** ${mod.modId}\n` +
                        `- **Path:** ${mod.path}\n` +
                        `- **Exists:** ${mod.exists ? 'Yes' : 'No'}`
                    );
                    
                    if (!mod.exists) {
                        item.iconPath = new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground'));
                    }
                    
                    return item;
                });
            } catch (error) {
                this.logger.error('Failed to load live mods', error);
                return [
                    new LiveModTreeItem(
                        'Failed to load live mods',
                        vscode.TreeItemCollapsibleState.None,
                        'category'
                    )
                ];
            }
        }

        if (element.itemType === 'mod' && element.mod) {
            // Show mod contents categories
            const categories = [
                { name: 'common', icon: 'folder' },
                { name: 'events', icon: 'folder' },
                { name: 'localization', icon: 'folder' },
                { name: 'gfx', icon: 'folder' },
                { name: 'gui', icon: 'folder' }
            ];

            const items: LiveModTreeItem[] = [];

            // Add Git status if available
            try {
                const status = await this.session.getGitStatus(element.mod.name);
                if (status) {
                    const changedCount = status.staged.length + status.unstaged.length + status.untracked.length;
                    if (changedCount > 0) {
                        const gitItem = new LiveModTreeItem(
                            `Git: ${changedCount} changes`,
                            vscode.TreeItemCollapsibleState.Collapsed,
                            'category',
                            element.mod,
                            { gitStatus: status }
                        );
                        gitItem.iconPath = new vscode.ThemeIcon('git-branch');
                        gitItem.description = `${status.staged.length} staged, ${status.unstaged.length} modified`;
                        items.push(gitItem);
                    }
                }
            } catch {
                // Git not available for this mod
            }

            // Add folder categories
            for (const cat of categories) {
                const catItem = new LiveModTreeItem(
                    cat.name,
                    vscode.TreeItemCollapsibleState.Collapsed,
                    'category',
                    element.mod,
                    { folder: cat.name }
                );
                items.push(catItem);
            }

            return items;
        }

        if (element.itemType === 'category' && element.data?.gitStatus) {
            // Show git changes
            const status = element.data.gitStatus;
            const items: LiveModTreeItem[] = [];

            for (const file of status.staged) {
                const item = new LiveModTreeItem(
                    file,
                    vscode.TreeItemCollapsibleState.None,
                    'file',
                    element.mod
                );
                item.iconPath = new vscode.ThemeIcon('check', new vscode.ThemeColor('gitDecoration.addedResourceForeground'));
                item.description = 'staged';
                items.push(item);
            }

            for (const file of status.unstaged) {
                const item = new LiveModTreeItem(
                    file,
                    vscode.TreeItemCollapsibleState.None,
                    'file',
                    element.mod
                );
                item.iconPath = new vscode.ThemeIcon('edit', new vscode.ThemeColor('gitDecoration.modifiedResourceForeground'));
                item.description = 'modified';
                items.push(item);
            }

            for (const file of status.untracked) {
                const item = new LiveModTreeItem(
                    file,
                    vscode.TreeItemCollapsibleState.None,
                    'file',
                    element.mod
                );
                item.iconPath = new vscode.ThemeIcon('question', new vscode.ThemeColor('gitDecoration.untrackedResourceForeground'));
                item.description = 'untracked';
                items.push(item);
            }

            return items;
        }

        if (element.itemType === 'category' && element.data?.folder && element.mod) {
            // TODO: List actual files in this folder
            // For now, return empty - this would require file listing from the mod
            return [];
        }

        return [];
    }
}
