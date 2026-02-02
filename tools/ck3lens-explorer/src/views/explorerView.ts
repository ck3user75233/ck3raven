/**
 * Explorer View Provider - Database-driven game state tree view
 * 
 * Displays the playset structure from ck3raven database:
 * - Mods in load order (vanilla first)
 * - Folder hierarchy within each mod
 * - Files with source tracking for provenance
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

/**
 * Tree item types for the explorer
 */
export type ExplorerItemType = 'playset' | 'mod' | 'folder' | 'file' | 'loading' | 'error';

/**
 * Extended tree item with CK3 metadata
 */
export class ExplorerTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: ExplorerItemType,
        public readonly data?: {
            path?: string;
            modName?: string;
            modId?: number;
            contentVersionId?: number;
            loadOrder?: number;
            relpath?: string;
            contentHash?: string;
            fileType?: string;
            absPath?: string;
        }
    ) {
        super(label, collapsibleState);
        this.contextValue = itemType;
        this.setupIcon();
        this.setupCommand();
    }

    private setupIcon(): void {
        switch (this.itemType) {
            case 'playset':
                this.iconPath = new vscode.ThemeIcon('list-ordered');
                break;
            case 'mod':
                this.iconPath = new vscode.ThemeIcon('package');
                break;
            case 'folder':
                this.iconPath = new vscode.ThemeIcon('folder');
                break;
            case 'file':
                // Different icons for different file types
                if (this.data?.fileType === 'text') {
                    this.iconPath = new vscode.ThemeIcon('file-code');
                } else if (this.data?.fileType === 'localization') {
                    this.iconPath = new vscode.ThemeIcon('symbol-text');
                } else {
                    this.iconPath = new vscode.ThemeIcon('file');
                }
                break;
            case 'loading':
                this.iconPath = new vscode.ThemeIcon('loading~spin');
                break;
            case 'error':
                this.iconPath = new vscode.ThemeIcon('error');
                break;
        }
    }

    private setupCommand(): void {
        if (this.itemType === 'file' && this.data?.relpath) {
            // Open in AST viewer when clicking a file
            this.command = {
                command: 'ck3lens.openAstViewer',
                title: 'View in AST Viewer',
                arguments: [
                    this.data.absPath ? vscode.Uri.file(this.data.absPath) : undefined,
                    this.data.modName || 'unknown'
                ]
            };
        }
    }

    /**
     * Create a mod badge showing load order
     */
    static createModBadge(loadOrder: number): string {
        return loadOrder === 0 ? '🎮' : `[${loadOrder}]`;
    }
}

/**
 * View mode for the explorer
 */
export type ViewMode = 'by-mod' | 'by-folder' | 'conflicts-only';

/**
 * Filter configuration
 */
export interface ExplorerFilter {
    folderPattern?: string;      // e.g., "common/on_action"
    textSearch?: string;         // Full-text search in content
    symbolSearch?: string;       // Symbol name search
    modFilter?: string[];        // Only show these mods
    fileTypeFilter?: string[];   // "text", "localization", "binary"
}

export class ExplorerViewProvider implements vscode.TreeDataProvider<ExplorerTreeItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<ExplorerTreeItem | undefined | null | void> = new vscode.EventEmitter();
    readonly onDidChangeTreeData: vscode.Event<ExplorerTreeItem | undefined | null | void> = this._onDidChangeTreeData.event;

    private viewMode: ViewMode = 'by-mod';
    private filter: ExplorerFilter = {};
    private cachedMods: Array<{
        name: string;
        contentVersionId: number;
        loadOrder: number;
        kind: string;
        fileCount: number;
        sourcePath?: string;
    }> = [];

    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    refresh(): void {
        this.cachedMods = [];
        this._onDidChangeTreeData.fire();
    }

    setViewMode(mode: ViewMode): void {
        this.viewMode = mode;
        this.refresh();
    }

    setFilter(filter: ExplorerFilter): void {
        this.filter = filter;
        this.refresh();
    }

    clearFilter(): void {
        this.filter = {};
        this.refresh();
    }

    getTreeItem(element: ExplorerTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: ExplorerTreeItem): Promise<ExplorerTreeItem[]> {
        console.log('[CK3RAVEN] ExplorerView.getChildren ENTER element=', element?.label);
        if (!this.session.isInitialized) {
            console.log('[CK3RAVEN] ExplorerView.getChildren EXIT (not initialized)');
            return [
                new ExplorerTreeItem(
                    'Click to initialize CK3 Lens',
                    vscode.TreeItemCollapsibleState.None,
                    'error',
                    {}
                )
            ];
        }

        try {
            if (!element) {
                // Root level
                return this.viewMode === 'by-mod' 
                    ? this.getRootByMod()
                    : this.getRootByFolder();
            }

            // Child nodes
            switch (element.itemType) {
                case 'mod':
                    return this.getModContents(element);
                case 'folder':
                    return this.getFolderContents(element);
                default:
                    return [];
            }
        } catch (error) {
            this.logger.error('Failed to get children', error);
            return [
                new ExplorerTreeItem(
                    `Error: ${error}`,
                    vscode.TreeItemCollapsibleState.None,
                    'error'
                )
            ];
        }
    }

    /**
     * Get root level - mods in load order
     */
    private async getRootByMod(): Promise<ExplorerTreeItem[]> {
        if (this.cachedMods.length === 0) {
            // Query playset mods from database
            const result = await this.session.getPlaysetMods();
            this.cachedMods = result;
        }

        if (this.cachedMods.length === 0) {
            return [
                new ExplorerTreeItem(
                    'No mods in playset',
                    vscode.TreeItemCollapsibleState.None,
                    'error'
                )
            ];
        }

        return this.cachedMods.map(mod => {
            const badge = ExplorerTreeItem.createModBadge(mod.loadOrder);
            const item = new ExplorerTreeItem(
                mod.name,
                vscode.TreeItemCollapsibleState.Collapsed,
                'mod',
                {
                    modName: mod.name,
                    contentVersionId: mod.contentVersionId,
                    loadOrder: mod.loadOrder,
                    path: mod.sourcePath
                }
            );
            item.description = `${badge} ${mod.fileCount} files`;
            item.tooltip = new vscode.MarkdownString(
                `**${mod.name}**\n\n` +
                `- Load Order: ${mod.loadOrder}\n` +
                `- Files: ${mod.fileCount}\n` +
                `- Kind: ${mod.kind}\n` +
                (mod.sourcePath ? `- Path: ${mod.sourcePath}` : '')
            );
            return item;
        });
    }

    /**
     * Get root level - top-level folders across all mods
     */
    private async getRootByFolder(): Promise<ExplorerTreeItem[]> {
        const folders = await this.session.getTopLevelFolders();
        
        return folders.map(f => {
            const item = new ExplorerTreeItem(
                f.name,
                vscode.TreeItemCollapsibleState.Collapsed,
                'folder',
                { path: f.name }
            );
            item.description = `${f.fileCount} files`;
            return item;
        });
    }

    /**
     * Get contents of a mod - top-level folders
     */
    private async getModContents(element: ExplorerTreeItem): Promise<ExplorerTreeItem[]> {
        const contentVersionId = element.data?.contentVersionId;
        if (!contentVersionId) {
            return [];
        }

        const folders = await this.session.getModFolders(contentVersionId);
        
        return folders.map(folder => {
            const item = new ExplorerTreeItem(
                folder.name,
                vscode.TreeItemCollapsibleState.Collapsed,
                'folder',
                {
                    path: folder.name,
                    modName: element.data?.modName,
                    contentVersionId: contentVersionId,
                    loadOrder: element.data?.loadOrder
                }
            );
            item.description = `${folder.fileCount} files`;
            return item;
        });
    }

    /**
     * Get contents of a folder - subfolders and files
     */
    private async getFolderContents(element: ExplorerTreeItem): Promise<ExplorerTreeItem[]> {
        const path = element.data?.path || '';
        const contentVersionId = element.data?.contentVersionId;
        
        // Get subfolders and files for this path
        const contents = await this.session.getFolderContents(
            path,
            contentVersionId,
            this.filter
        );
        
        const items: ExplorerTreeItem[] = [];
        
        // Add subfolders first
        for (const folder of contents.folders) {
            items.push(new ExplorerTreeItem(
                folder.name,
                vscode.TreeItemCollapsibleState.Collapsed,
                'folder',
                {
                    path: `${path}/${folder.name}`,
                    modName: element.data?.modName,
                    contentVersionId: contentVersionId,
                    loadOrder: element.data?.loadOrder
                }
            ));
        }
        
        // Add files
        for (const file of contents.files) {
            const fileName = file.relpath.split('/').pop() || file.relpath;
            const item = new ExplorerTreeItem(
                fileName,
                vscode.TreeItemCollapsibleState.None,
                'file',
                {
                    relpath: file.relpath,
                    modName: element.data?.modName || file.modName,
                    contentVersionId: contentVersionId,
                    contentHash: file.contentHash,
                    fileType: file.fileType,
                    absPath: file.absPath,
                    loadOrder: element.data?.loadOrder
                }
            );
            
            // Show mod name if viewing by folder (files from multiple mods)
            if (this.viewMode === 'by-folder' && file.modName) {
                item.description = file.modName;
            }
            
            item.tooltip = new vscode.MarkdownString(
                `**${file.relpath}**\n\n` +
                `- Mod: ${file.modName || 'unknown'}\n` +
                `- Type: ${file.fileType}\n` +
                `- Hash: ${file.contentHash?.substring(0, 12)}...`
            );
            
            items.push(item);
        }
        
        return items;
    }
}
