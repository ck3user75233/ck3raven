/**
 * Journal Tree Provider
 * 
 * TreeDataProvider for browsing archived journal sessions in the VS Code sidebar.
 * 
 * Hierarchy:
 *   Workspace (by display name or key)
 *     └── Window (by timestamp)
 *           └── Session (by ID, clickable → opens .md file)
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { getJournalsBasePath, getWindowsPath, getWindowPath } from './storage';

/**
 * Tree item types for the journal explorer.
 */
export type JournalTreeItemType = 'workspace' | 'window' | 'session';

/**
 * Context value for tree items (used in when clauses).
 */
const CONTEXT_VALUES = {
    workspace: 'journalWorkspace',
    window: 'journalWindow',
    session: 'journalSession',
} as const;

/**
 * Tree item representing a node in the journal hierarchy.
 */
export class JournalTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly itemType: JournalTreeItemType,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly workspaceKey?: string,
        public readonly windowId?: string,
        public readonly sessionId?: string,
        public readonly filePath?: string,
    ) {
        super(label, collapsibleState);

        this.contextValue = CONTEXT_VALUES[itemType];

        // Set icons based on type
        switch (itemType) {
            case 'workspace':
                this.iconPath = new vscode.ThemeIcon('folder');
                this.tooltip = `Workspace: ${workspaceKey}`;
                break;
            case 'window':
                this.iconPath = new vscode.ThemeIcon('window');
                this.tooltip = `Window: ${windowId}`;
                this.description = this.formatWindowTimestamp(windowId || '');
                break;
            case 'session':
                this.iconPath = new vscode.ThemeIcon('comment-discussion');
                this.tooltip = `Session: ${sessionId}\nClick to open`;
                this.description = sessionId?.substring(0, 8) + '...';
                // Make session clickable
                if (filePath) {
                    this.command = {
                        command: 'vscode.open',
                        title: 'Open Session',
                        arguments: [vscode.Uri.file(filePath)],
                    };
                }
                break;
        }
    }

    /**
     * Format window ID timestamp for display.
     * Input: "2026-02-02T06-38-25Z_window-4703"
     * Output: "Feb 2, 2:38 PM"
     */
    private formatWindowTimestamp(windowId: string): string {
        const match = windowId.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})Z/);
        if (!match) {
            return '';
        }

        const [, year, month, day, hour, minute] = match;
        const date = new Date(
            parseInt(year),
            parseInt(month) - 1,
            parseInt(day),
            parseInt(hour),
            parseInt(minute)
        );

        return date.toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        });
    }
}

/**
 * TreeDataProvider for journal archives.
 */
export class JournalTreeProvider implements vscode.TreeDataProvider<JournalTreeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<JournalTreeItem | undefined | null | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    /**
     * Refresh the entire tree.
     */
    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    /**
     * Get the tree item representation for an element.
     */
    getTreeItem(element: JournalTreeItem): vscode.TreeItem {
        return element;
    }

    /**
     * Get children for a tree node.
     */
    getChildren(element?: JournalTreeItem): Thenable<JournalTreeItem[]> {
        if (!element) {
            // Root level: list workspaces
            return Promise.resolve(this.getWorkspaces());
        }

        switch (element.itemType) {
            case 'workspace':
                return Promise.resolve(this.getWindows(element.workspaceKey!));
            case 'window':
                return Promise.resolve(this.getSessions(element.workspaceKey!, element.windowId!));
            case 'session':
                return Promise.resolve([]); // Sessions have no children
            default:
                return Promise.resolve([]);
        }
    }

    /**
     * List all workspace directories.
     */
    private getWorkspaces(): JournalTreeItem[] {
        const basePath = getJournalsBasePath();

        if (!fs.existsSync(basePath)) {
            return [];
        }

        try {
            const entries = fs.readdirSync(basePath, { withFileTypes: true });
            return entries
                .filter(e => e.isDirectory())
                .map(e => new JournalTreeItem(
                    this.getWorkspaceDisplayName(e.name),
                    'workspace',
                    vscode.TreeItemCollapsibleState.Collapsed,
                    e.name, // workspaceKey
                ))
                .sort((a, b) => a.label.toString().localeCompare(b.label.toString()));
        } catch {
            return [];
        }
    }

    /**
     * Get display name for a workspace key.
     * For now, just show the first 8 chars of the hash.
     * Future: could read a metadata file with the original workspace name.
     */
    private getWorkspaceDisplayName(workspaceKey: string): string {
        // Could be enhanced to read a metadata file
        return `Workspace ${workspaceKey.substring(0, 8)}`;
    }

    /**
     * List all window directories for a workspace.
     */
    private getWindows(workspaceKey: string): JournalTreeItem[] {
        const windowsPath = getWindowsPath(workspaceKey);

        if (!fs.existsSync(windowsPath)) {
            return [];
        }

        try {
            const entries = fs.readdirSync(windowsPath, { withFileTypes: true });
            return entries
                .filter(e => e.isDirectory())
                .map(e => new JournalTreeItem(
                    e.name,
                    'window',
                    vscode.TreeItemCollapsibleState.Collapsed,
                    workspaceKey,
                    e.name, // windowId
                ))
                .sort((a, b) => b.label.toString().localeCompare(a.label.toString())); // Newest first
        } catch {
            return [];
        }
    }

    /**
     * List all session files in a window directory.
     */
    private getSessions(workspaceKey: string, windowId: string): JournalTreeItem[] {
        const windowPath = getWindowPath(workspaceKey, windowId);

        if (!fs.existsSync(windowPath)) {
            return [];
        }

        try {
            const entries = fs.readdirSync(windowPath, { withFileTypes: true });
            return entries
                .filter(e => e.isFile() && e.name.endsWith('.md') && e.name !== 'manifest.md')
                .map(e => {
                    const sessionId = e.name.replace('.md', '');
                    const filePath = path.join(windowPath, e.name);
                    return new JournalTreeItem(
                        this.getSessionDisplayName(filePath, sessionId),
                        'session',
                        vscode.TreeItemCollapsibleState.None,
                        workspaceKey,
                        windowId,
                        sessionId,
                        filePath,
                    );
                });
        } catch {
            return [];
        }
    }

    /**
     * Get display name for a session.
     * Tries to extract the first user message as a preview.
     */
    private getSessionDisplayName(filePath: string, sessionId: string): string {
        try {
            const content = fs.readFileSync(filePath, 'utf-8');
            // Look for first user message content
            const userMatch = content.match(/## 👤 User \(1\)\s*\n\n\*[^*]+\*\s*\n\n(.+)/);
            if (userMatch) {
                const preview = userMatch[1].substring(0, 40).trim();
                return preview.length < userMatch[1].length ? preview + '...' : preview;
            }
        } catch {
            // Fall through to default
        }
        return `Session ${sessionId.substring(0, 8)}`;
    }

    /**
     * Dispose resources.
     */
    dispose(): void {
        this._onDidChangeTreeData.dispose();
    }
}

/**
 * Create and register the journal tree view.
 * 
 * @param context - Extension context for registrations
 * @returns The tree data provider (for refresh commands)
 */
export function registerJournalTreeView(
    context: vscode.ExtensionContext
): JournalTreeProvider {
    const treeProvider = new JournalTreeProvider();

    // Register the tree view
    const treeView = vscode.window.createTreeView('ck3lens.journalExplorer', {
        treeDataProvider: treeProvider,
        showCollapseAll: true,
    });

    // Register refresh command
    const refreshCommand = vscode.commands.registerCommand(
        'ck3lens.journal.refresh',
        () => treeProvider.refresh()
    );

    // Register open in explorer command
    const openFolderCommand = vscode.commands.registerCommand(
        'ck3lens.journal.openFolder',
        () => {
            const basePath = getJournalsBasePath();
            if (fs.existsSync(basePath)) {
                vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(basePath));
            } else {
                vscode.window.showInformationMessage('No journals directory exists yet.');
            }
        }
    );

    context.subscriptions.push(treeView, refreshCommand, openFolderCommand, treeProvider);

    return treeProvider;
}
