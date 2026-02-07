/**
 * Journal Tree Provider
 * 
 * TreeDataProvider for browsing archived journal sessions in the VS Code sidebar.
 * 
 * Hierarchy (date-based grouping):
 *   Today
 *     └── Session (clickable → opens .md file)
 *   This Week
 *     └── Session
 *   This Month
 *     └── Session
 *   Older
 *     └── Session
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { getJournalsBasePath, getChatArchivesPath } from './storage';

/**
 * Tree item types for the journal explorer.
 */
export type JournalTreeItemType = 'date-group' | 'session';

/**
 * Date group categories for organizing sessions.
 */
export type DateGroup = 'today' | 'this-week' | 'this-month' | 'older';

/**
 * Context value for tree items (used in when clauses).
 */
const CONTEXT_VALUES = {
    'date-group': 'journalDateGroup',
    session: 'journalSession',
} as const;

/**
 * Display labels for date groups.
 */
const DATE_GROUP_LABELS: Record<DateGroup, string> = {
    'today': 'Today',
    'this-week': 'This Week',
    'this-month': 'This Month',
    'older': 'Older',
};

/**
 * Icons for date groups.
 */
const DATE_GROUP_ICONS: Record<DateGroup, string> = {
    'today': 'calendar',
    'this-week': 'calendar',
    'this-month': 'calendar',
    'older': 'archive',
};

/**
 * Session info with metadata for sorting/grouping.
 */
interface SessionInfo {
    sessionId: string;
    filePath: string;
    workspaceKey: string;
    mtime: Date;
    size: number;
    displayName: string;
}

/**
 * Tree item representing a node in the journal hierarchy.
 */
export class JournalTreeItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly itemType: JournalTreeItemType,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly dateGroup?: DateGroup,
        public readonly sessionInfo?: SessionInfo,
    ) {
        super(label, collapsibleState);

        this.contextValue = CONTEXT_VALUES[itemType];

        // Set icons based on type
        switch (itemType) {
            case 'date-group':
                this.iconPath = new vscode.ThemeIcon(DATE_GROUP_ICONS[dateGroup!] || 'folder');
                this.tooltip = `${DATE_GROUP_LABELS[dateGroup!]} sessions`;
                break;
            case 'session':
                this.iconPath = new vscode.ThemeIcon('comment-discussion');
                if (sessionInfo) {
                    const timeStr = this.formatTime(sessionInfo.mtime);
                    this.description = `${timeStr} · ${this.formatFileSize(sessionInfo.size)}`;
                    this.tooltip = new vscode.MarkdownString(
                        `**${sessionInfo.displayName}**\n\n` +
                        `Time: ${sessionInfo.mtime.toLocaleString()}\n\n` +
                        `Size: ${this.formatFileSize(sessionInfo.size)}\n\n` +
                        `Click to open`
                    );
                    // Make session clickable
                    this.command = {
                        command: 'vscode.open',
                        title: 'Open Session',
                        arguments: [vscode.Uri.file(sessionInfo.filePath)],
                    };
                }
                break;
        }
    }

    /**
     * Format file size for display.
     */
    private formatFileSize(bytes: number): string {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    /**
     * Format time for display (time if today, date otherwise).
     */
    private formatTime(date: Date): string {
        const now = new Date();
        const isToday = date.toDateString() === now.toDateString();
        
        if (isToday) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
}

/**
 * TreeDataProvider for journal archives with date-based grouping.
 */
export class JournalTreeProvider implements vscode.TreeDataProvider<JournalTreeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<JournalTreeItem | undefined | null | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    // Cached sessions for grouping
    private cachedSessions: SessionInfo[] = [];
    private cacheTime: number = 0;
    private readonly CACHE_TTL_MS = 5000; // Refresh cache every 5 seconds

    /**
     * Refresh the entire tree.
     */
    refresh(): void {
        this.cacheTime = 0; // Invalidate cache
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
            // Root level: return date groups that have sessions
            return Promise.resolve(this.getDateGroups());
        }

        switch (element.itemType) {
            case 'date-group':
                return Promise.resolve(this.getSessionsForDateGroup(element.dateGroup!));
            case 'session':
                return Promise.resolve([]); // Sessions have no children
            default:
                return Promise.resolve([]);
        }
    }

    /**
     * Load all sessions from all workspaces.
     */
    private loadAllSessions(): SessionInfo[] {
        // Check cache
        const now = Date.now();
        if (this.cachedSessions.length > 0 && (now - this.cacheTime) < this.CACHE_TTL_MS) {
            return this.cachedSessions;
        }

        const basePath = getJournalsBasePath();
        const sessions: SessionInfo[] = [];

        if (!fs.existsSync(basePath)) {
            this.cachedSessions = [];
            this.cacheTime = now;
            return [];
        }

        try {
            // Iterate all workspace directories
            const workspaces = fs.readdirSync(basePath, { withFileTypes: true })
                .filter(e => e.isDirectory());

            for (const ws of workspaces) {
                const archivesPath = getChatArchivesPath(ws.name);
                if (!fs.existsSync(archivesPath)) continue;

                const files = fs.readdirSync(archivesPath, { withFileTypes: true })
                    .filter(e => e.isFile() && e.name.endsWith('.md'));

                for (const file of files) {
                    const sessionId = file.name.replace('.md', '');
                    const filePath = path.join(archivesPath, file.name);
                    try {
                        const stats = fs.statSync(filePath);
                        sessions.push({
                            sessionId,
                            filePath,
                            workspaceKey: ws.name,
                            mtime: stats.mtime,
                            size: stats.size,
                            displayName: this.getSessionDisplayName(filePath, sessionId),
                        });
                    } catch {
                        // Skip files we can't stat
                    }
                }
            }
        } catch {
            // Return empty on error
        }

        // Sort by mtime descending (newest first)
        sessions.sort((a, b) => b.mtime.getTime() - a.mtime.getTime());

        this.cachedSessions = sessions;
        this.cacheTime = now;
        return sessions;
    }

    /**
     * Get date groups that have at least one session.
     */
    private getDateGroups(): JournalTreeItem[] {
        const sessions = this.loadAllSessions();
        if (sessions.length === 0) {
            return [];
        }

        const groups = this.groupSessionsByDate(sessions);
        const result: JournalTreeItem[] = [];

        // Return groups in order, only if they have sessions
        const groupOrder: DateGroup[] = ['today', 'this-week', 'this-month', 'older'];
        for (const group of groupOrder) {
            if (groups[group].length > 0) {
                result.push(new JournalTreeItem(
                    `${DATE_GROUP_LABELS[group]} (${groups[group].length})`,
                    'date-group',
                    vscode.TreeItemCollapsibleState.Collapsed,
                    group,
                ));
            }
        }

        // If only one group, expand it by default
        if (result.length === 1) {
            result[0] = new JournalTreeItem(
                result[0].label as string,
                'date-group',
                vscode.TreeItemCollapsibleState.Expanded,
                result[0].dateGroup,
            );
        }

        return result;
    }

    /**
     * Get sessions for a specific date group.
     */
    private getSessionsForDateGroup(dateGroup: DateGroup): JournalTreeItem[] {
        const sessions = this.loadAllSessions();
        const groups = this.groupSessionsByDate(sessions);

        return groups[dateGroup].map(s => new JournalTreeItem(
            s.displayName,
            'session',
            vscode.TreeItemCollapsibleState.None,
            undefined,
            s,
        ));
    }

    /**
     * Group sessions by date category.
     */
    private groupSessionsByDate(sessions: SessionInfo[]): Record<DateGroup, SessionInfo[]> {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
        const monthAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);

        const groups: Record<DateGroup, SessionInfo[]> = {
            'today': [],
            'this-week': [],
            'this-month': [],
            'older': [],
        };

        for (const session of sessions) {
            const mtime = session.mtime;
            if (mtime >= today) {
                groups['today'].push(session);
            } else if (mtime >= weekAgo) {
                groups['this-week'].push(session);
            } else if (mtime >= monthAgo) {
                groups['this-month'].push(session);
            } else {
                groups['older'].push(session);
            }
        }

        return groups;
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
