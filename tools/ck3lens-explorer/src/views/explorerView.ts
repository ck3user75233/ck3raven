/**
 * Explorer View Provider - Game state tree view
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

export class ExplorerTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: 'folder' | 'file' | 'symbol' | 'mod',
        public readonly data?: any
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;
        
        // Set icons based on type
        switch (itemType) {
            case 'folder':
                this.iconPath = new vscode.ThemeIcon('folder');
                break;
            case 'file':
                this.iconPath = new vscode.ThemeIcon('file');
                break;
            case 'symbol':
                this.iconPath = new vscode.ThemeIcon('symbol-property');
                break;
            case 'mod':
                this.iconPath = new vscode.ThemeIcon('package');
                break;
        }
    }
}

export class ExplorerViewProvider implements vscode.TreeDataProvider<ExplorerTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<ExplorerTreeItem | undefined | null | void> = new vscode.EventEmitter();
    readonly onDidChangeTreeData: vscode.Event<ExplorerTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: ExplorerTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: ExplorerTreeItem): Promise<ExplorerTreeItem[]> {
        if (!this.session.isInitialized) {
            return [
                new ExplorerTreeItem(
                    'Click to initialize CK3 Lens',
                    vscode.TreeItemCollapsibleState.None,
                    'folder'
                )
            ];
        }

        if (!element) {
            // Root level - show main folders
            return this.getRootItems();
        }

        if (element.itemType === 'folder') {
            return this.getFolderContents(element);
        }

        return [];
    }

    private async getRootItems(): Promise<ExplorerTreeItem[]> {
        const folders = [
            { name: 'common', desc: 'Game definitions' },
            { name: 'events', desc: 'Event files' },
            { name: 'gfx', desc: 'Graphics' },
            { name: 'localization', desc: 'Text strings' },
            { name: 'gui', desc: 'Interface files' },
            { name: 'history', desc: 'Historical setup' },
            { name: 'map_data', desc: 'Map data' }
        ];

        return folders.map(f => {
            const item = new ExplorerTreeItem(
                f.name,
                vscode.TreeItemCollapsibleState.Collapsed,
                'folder',
                { path: f.name }
            );
            item.description = f.desc;
            item.tooltip = `${f.name} - ${f.desc}`;
            return item;
        });
    }

    private async getFolderContents(element: ExplorerTreeItem): Promise<ExplorerTreeItem[]> {
        const folderPath = element.data?.path || element.label;
        
        // Get subfolders for common content types
        const subfolders: { [key: string]: string[] } = {
            'common': [
                'traits', 'cultures', 'religions', 'decisions', 'on_action',
                'scripted_effects', 'scripted_triggers', 'events', 'buildings',
                'character_interactions', 'laws', 'governments', 'artifacts',
                'court_positions', 'schemes', 'dynasties', 'defines', 'modifiers',
                'casus_belli', 'story_cycles', 'activities', 'struggles'
            ],
            'events': [
                'activities_events', 'character_events', 'court_events',
                'culture_events', 'decision_events', 'dlc_events',
                'dynasty_events', 'faith_events', 'health_events',
                'interaction_events', 'lifestyle_events', 'scheme_events',
                'secret_events', 'story_cycle_events', 'struggle_events',
                'war_events'
            ],
            'localization': [
                'english', 'french', 'german', 'spanish', 'russian',
                'simp_chinese', 'korean', 'braz_por', 'polish'
            ]
        };

        const children = subfolders[folderPath as string] || [];
        
        if (children.length === 0) {
            // Try to get actual files from the database
            try {
                const files = await this.session.listFiles(folderPath as string);
                return files.map(f => {
                    const item = new ExplorerTreeItem(
                        f.relpath.split('/').pop() || f.relpath,
                        vscode.TreeItemCollapsibleState.None,
                        'file',
                        f
                    );
                    item.description = f.mod;
                    item.tooltip = `${f.relpath}\nMod: ${f.mod}\nSize: ${f.size} bytes`;
                    item.command = {
                        command: 'vscode.open',
                        title: 'Open File',
                        arguments: [vscode.Uri.file(f.relpath)]
                    };
                    return item;
                });
            } catch (error) {
                this.logger.error('Failed to get folder contents', error);
                return [];
            }
        }

        return children.map(name => {
            const item = new ExplorerTreeItem(
                name,
                vscode.TreeItemCollapsibleState.Collapsed,
                'folder',
                { path: `${folderPath}/${name}` }
            );
            return item;
        });
    }
}
