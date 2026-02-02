/**
 * Playset View Provider - Show mods in active playset with load order
 */

import * as vscode from 'vscode';
import { CK3LensSession, PlaysetModInfo } from '../session';
import { Logger } from '../utils/logger';

const PLAYSET_ITEM_MIME_TYPE = 'application/vnd.code.tree.ck3lens-playset';

export class PlaysetTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: 'mod' | 'header' | 'info',
        public readonly mod?: PlaysetModInfo,
        public readonly loadOrder?: number
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;

        switch (itemType) {
            case 'mod':
                // Different icons based on mod kind
                if (mod?.kind === 'vanilla') {
                    this.iconPath = new vscode.ThemeIcon('verified', new vscode.ThemeColor('charts.blue'));
                } else if (mod?.kind === 'steam') {
                    this.iconPath = new vscode.ThemeIcon('cloud-download');
                } else {
                    this.iconPath = new vscode.ThemeIcon('package');
                }
                break;
            case 'header':
                this.iconPath = new vscode.ThemeIcon('list-ordered');
                break;
            case 'info':
                this.iconPath = new vscode.ThemeIcon('info');
                break;
        }
    }
}

export class PlaysetViewProvider implements vscode.TreeDataProvider<PlaysetTreeItem>, vscode.TreeDragAndDropController<PlaysetTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<PlaysetTreeItem | undefined | null | void> = new vscode.EventEmitter();
    readonly onDidChangeTreeData: vscode.Event<PlaysetTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    // Drag and drop
    readonly dragMimeTypes = [PLAYSET_ITEM_MIME_TYPE];
    readonly dropMimeTypes = [PLAYSET_ITEM_MIME_TYPE];

    private playsetMods: PlaysetModInfo[] = [];
    private playsetName: string | null = null;

    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    // Drag and drop implementation
    handleDrag(source: readonly PlaysetTreeItem[], dataTransfer: vscode.DataTransfer, token: vscode.CancellationToken): void | Thenable<void> {
        const modsToMove = source.filter(item => item.itemType === 'mod' && item.mod);
        if (modsToMove.length === 0) {
            return;
        }

        // Store the mod data for transfer
        const transferData = modsToMove.map(item => ({
            name: item.mod!.name,
            contentVersionId: item.mod!.contentVersionId,
            loadOrder: item.loadOrder
        }));

        dataTransfer.set(PLAYSET_ITEM_MIME_TYPE, new vscode.DataTransferItem(transferData));
    }

    async handleDrop(target: PlaysetTreeItem | undefined, dataTransfer: vscode.DataTransfer, token: vscode.CancellationToken): Promise<void> {
        const transferItem = dataTransfer.get(PLAYSET_ITEM_MIME_TYPE);
        if (!transferItem) {
            return;
        }

        const droppedMods = transferItem.value as Array<{ name: string; contentVersionId: number; loadOrder: number }>;
        if (!droppedMods || droppedMods.length === 0) {
            return;
        }

        // Determine target position
        let targetPosition: number;
        if (!target || target.itemType === 'header') {
            // Dropped on header or empty space - move to top (position 1, after vanilla at 0)
            targetPosition = 1;
        } else if (target.itemType === 'mod' && target.loadOrder !== undefined) {
            // Dropped on a mod - move to that position
            targetPosition = target.loadOrder;
        } else {
            return;
        }

        // Reorder each mod
        for (const mod of droppedMods) {
            try {
                await this.session.reorderMod(mod.name, targetPosition);
                this.logger.info(`Moved ${mod.name} to position ${targetPosition}`);
            } catch (error) {
                this.logger.error(`Failed to reorder ${mod.name}`, error);
                vscode.window.showErrorMessage(`Failed to reorder ${mod.name}: ${error}`);
            }
        }

        // Refresh the view
        this.refresh();
    }

    getTreeItem(element: PlaysetTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: PlaysetTreeItem): Promise<PlaysetTreeItem[]> {
        console.log('[CK3RAVEN] PlaysetView.getChildren ENTER element=', element?.label);
        if (!element) {
            // Root level - show playset info and mods
            if (!this.session.isInitialized) {
                console.log('[CK3RAVEN] PlaysetView.getChildren EXIT (not initialized)');
                return [
                    new PlaysetTreeItem(
                        'Initialize CK3 Lens to see playset',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    )
                ];
            }

            try {
                // Get session info for playset name
                const sessionInfo = this.session.sessionInfo;
                this.playsetName = sessionInfo?.playsetName || 'Unknown Playset';

                // Get mods in playset
                this.playsetMods = await this.session.getPlaysetMods();
                
                if (this.playsetMods.length === 0) {
                    const emptyItem = new PlaysetTreeItem(
                        'No mods in playset',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    );
                    emptyItem.description = 'Click to configure';
                    emptyItem.command = {
                        command: 'ck3lens.setupPlayset',
                        title: 'Setup Active Playset'
                    };
                    
                    const addModItem = new PlaysetTreeItem(
                        '+ Add mods to playset',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    );
                    addModItem.iconPath = new vscode.ThemeIcon('add');
                    addModItem.command = {
                        command: 'ck3lens.setupPlayset',
                        title: 'Setup Active Playset'
                    };
                    
                    const switchPlaysetItem = new PlaysetTreeItem(
                        'Switch to different playset',
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    );
                    switchPlaysetItem.iconPath = new vscode.ThemeIcon('list-selection');
                    switchPlaysetItem.command = {
                        command: 'ck3lens.viewPlaysets',
                        title: 'View All Playsets'
                    };
                    
                    return [emptyItem, addModItem, switchPlaysetItem];
                }

                // Create header with playset name and mod count
                const items: PlaysetTreeItem[] = [];
                
                // Header showing playset name
                const headerItem = new PlaysetTreeItem(
                    `${this.playsetName} (${this.playsetMods.length} mods)`,
                    vscode.TreeItemCollapsibleState.Expanded,
                    'header'
                );
                headerItem.description = 'Active Playset';
                items.push(headerItem);

                return items;
            } catch (error) {
                this.logger.error('Failed to load playset mods', error);
                return [
                    new PlaysetTreeItem(
                        `Error: ${error}`,
                        vscode.TreeItemCollapsibleState.None,
                        'info'
                    )
                ];
            }
        }

        // Children of header - show mods
        if (element.itemType === 'header') {
            return this.playsetMods.map((mod, index) => {
                const loadOrder = mod.loadOrder ?? index;
                const item = new PlaysetTreeItem(
                    `${loadOrder + 1}. ${mod.name}`,
                    vscode.TreeItemCollapsibleState.None,
                    'mod',
                    mod,
                    loadOrder
                );
                
                // Description shows kind and file count
                item.description = `${mod.kind || 'local'} · ${mod.fileCount} files`;
                
                // Rich tooltip with all info
                item.tooltip = new vscode.MarkdownString(
                    `**${mod.name}**\n\n` +
                    `- **Load Order:** ${loadOrder + 1}\n` +
                    `- **Content Version ID:** ${mod.contentVersionId}\n` +
                    `- **Type:** ${mod.kind || 'local'}\n` +
                    `- **Files:** ${mod.fileCount}\n` +
                    (mod.sourcePath ? `- **Path:** ${mod.sourcePath}\n` : '')
                );

                // Context menu command to open mod folder
                if (mod.sourcePath) {
                    item.command = {
                        command: 'revealFileInOS',
                        title: 'Open Mod Folder',
                        arguments: [vscode.Uri.file(mod.sourcePath)]
                    };
                }

                return item;
            });
        }

        return [];
    }
}
