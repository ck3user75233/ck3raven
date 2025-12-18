/**
 * Symbols View Provider - Search and browse symbols
 */

import * as vscode from 'vscode';
import { CK3LensSession, SymbolResult } from '../session';
import { Logger } from '../utils/logger';

export class SymbolTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: 'symbol' | 'category' | 'search',
        public readonly symbol?: SymbolResult
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;

        if (symbol) {
            this.setSymbolIcon(symbol.symbolType);
        } else if (itemType === 'category') {
            this.iconPath = new vscode.ThemeIcon('folder');
        } else if (itemType === 'search') {
            this.iconPath = new vscode.ThemeIcon('search');
        }
    }

    private setSymbolIcon(symbolType: string): void {
        const iconMap: { [key: string]: string } = {
            'trait': 'symbol-property',
            'event': 'symbol-event',
            'decision': 'symbol-method',
            'on_action': 'symbol-event',
            'scripted_effect': 'symbol-function',
            'scripted_trigger': 'symbol-boolean',
            'culture': 'symbol-class',
            'religion': 'symbol-namespace',
            'faith': 'symbol-namespace',
            'building': 'symbol-constructor',
            'government': 'symbol-struct',
            'law': 'symbol-ruler',
            'tradition': 'symbol-interface',
            'artifact': 'symbol-key',
            'scheme': 'symbol-method',
            'dynasty': 'symbol-class',
            'character': 'person',
            'title': 'symbol-ruler'
        };

        const icon = iconMap[symbolType] || 'symbol-misc';
        this.iconPath = new vscode.ThemeIcon(icon);
    }
}

export class SymbolsViewProvider implements vscode.TreeDataProvider<SymbolTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<SymbolTreeItem | undefined | null | void> = new vscode.EventEmitter();
    readonly onDidChangeTreeData: vscode.Event<SymbolTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    private searchResults: SymbolResult[] = [];
    private searchQuery: string = '';

    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    showSearchResults(results: SymbolResult[], query?: string): void {
        this.searchResults = results;
        this.searchQuery = query || '';
        this.refresh();
    }

    clearResults(): void {
        this.searchResults = [];
        this.searchQuery = '';
        this.refresh();
    }

    getTreeItem(element: SymbolTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: SymbolTreeItem): Promise<SymbolTreeItem[]> {
        if (!element) {
            // Root level
            if (this.searchResults.length > 0) {
                // Show search results header
                const header = new SymbolTreeItem(
                    `Search: "${this.searchQuery}" (${this.searchResults.length} results)`,
                    vscode.TreeItemCollapsibleState.Expanded,
                    'search'
                );
                return [header];
            }

            // Show symbol type categories
            const categories = [
                { name: 'Traits', type: 'trait' },
                { name: 'Events', type: 'event' },
                { name: 'Decisions', type: 'decision' },
                { name: 'On Actions', type: 'on_action' },
                { name: 'Scripted Effects', type: 'scripted_effect' },
                { name: 'Scripted Triggers', type: 'scripted_trigger' },
                { name: 'Cultures', type: 'culture' },
                { name: 'Religions', type: 'religion' },
                { name: 'Buildings', type: 'building' },
                { name: 'Traditions', type: 'tradition' }
            ];

            return categories.map(cat => {
                const item = new SymbolTreeItem(
                    cat.name,
                    vscode.TreeItemCollapsibleState.Collapsed,
                    'category'
                );
                item.description = cat.type;
                return item;
            });
        }

        if (element.itemType === 'search') {
            // Show search results
            return this.searchResults.map(symbol => this.createSymbolItem(symbol));
        }

        if (element.itemType === 'category') {
            // Load symbols of this type
            try {
                const symbolType = element.description as string;
                const results = await this.session.searchSymbols('', symbolType, 100);
                return results.map(symbol => this.createSymbolItem(symbol));
            } catch (error) {
                this.logger.error('Failed to load symbols', error);
                return [];
            }
        }

        return [];
    }

    private createSymbolItem(symbol: SymbolResult): SymbolTreeItem {
        const item = new SymbolTreeItem(
            symbol.name,
            vscode.TreeItemCollapsibleState.None,
            'symbol',
            symbol
        );
        item.description = `${symbol.mod} • ${symbol.symbolType}`;
        item.tooltip = new vscode.MarkdownString(
            `**${symbol.name}**\n\n` +
            `- **Type:** ${symbol.symbolType}\n` +
            `- **Mod:** ${symbol.mod}\n` +
            `- **File:** ${symbol.relpath}\n` +
            `- **Line:** ${symbol.line}`
        );
        item.command = {
            command: 'vscode.open',
            title: 'Go to Symbol',
            arguments: [
                vscode.Uri.file(symbol.relpath),
                { selection: new vscode.Range(symbol.line - 1, 0, symbol.line - 1, 0) }
            ]
        };
        return item;
    }
}
