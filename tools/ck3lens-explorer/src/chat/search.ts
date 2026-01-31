/**
 * CK3 Raven Journal Search
 *
 * Simple text search across JSONL journal files.
 * V1 Brief: basic search for session review.
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as readline from 'readline';

/**
 * Search result
 */
export interface SearchResult {
    /** Path to the journal file */
    file: string;

    /** Line number (1-indexed) */
    lineNumber: number;

    /** The raw line content */
    line: string;

    /** Parsed event (if valid JSON) */
    event?: Record<string, unknown>;

    /** Match context snippet */
    matchContext: string;
}

/**
 * Search journal files for a query
 */
export async function searchJournals(
    journalFolder: vscode.Uri | undefined,
    query: string,
    options?: {
        maxResults?: number;
        dateFilter?: string; // YYYY-MM-DD
    }
): Promise<SearchResult[]> {
    if (!journalFolder) {
        return [];
    }

    const results: SearchResult[] = [];
    const maxResults = options?.maxResults ?? 100;
    const queryLower = query.toLowerCase();

    // Find all JSONL files
    const files = await findJournalFiles(journalFolder.fsPath, options?.dateFilter);

    for (const file of files) {
        if (results.length >= maxResults) break;

        const fileResults = await searchFile(file, queryLower, maxResults - results.length);
        results.push(...fileResults);
    }

    return results;
}

/**
 * Find all journal files, optionally filtered by date
 * Returns empty array if folder doesn't exist (not an error condition)
 */
async function findJournalFiles(
    folderPath: string,
    dateFilter?: string
): Promise<string[]> {
    const files: string[] = [];

    // Check if folder exists - not existing is valid (no journals yet)
    const folderExists = await fs.promises.access(folderPath).then(() => true).catch(() => false);
    if (!folderExists) {
        console.error(`[CK3RAVEN] Journal folder does not exist: ${folderPath}`);
        return [];
    }

    // List date folders
    const entries = await fs.promises.readdir(folderPath, { withFileTypes: true });

    for (const entry of entries) {
        if (!entry.isDirectory()) continue;

        // If date filter specified, only include matching folder
        if (dateFilter && entry.name !== dateFilter) continue;

        // Skip non-date folders
        if (!/^\d{4}-\d{2}-\d{2}$/.test(entry.name)) continue;

        const dayPath = path.join(folderPath, entry.name);
        const dayEntries = await fs.promises.readdir(dayPath);

        for (const file of dayEntries) {
            if (file.endsWith('.jsonl')) {
                files.push(path.join(dayPath, file));
            }
        }
    }

    // Sort by date descending (most recent first)
    return files.sort().reverse();
}

/**
 * Search a single file for matches
 */
async function searchFile(
    filePath: string,
    queryLower: string,
    maxResults: number
): Promise<SearchResult[]> {
    const results: SearchResult[] = [];

    const stream = fs.createReadStream(filePath, { encoding: 'utf-8' });
    const rl = readline.createInterface({
        input: stream,
        crlfDelay: Infinity
    });

    let lineNumber = 0;

    for await (const line of rl) {
        lineNumber++;
        if (results.length >= maxResults) break;

        // Case-insensitive search
        if (line.toLowerCase().includes(queryLower)) {
            let event: Record<string, unknown> | undefined;
            const parseResult = JSON.parse(line);
            if (typeof parseResult === 'object' && parseResult !== null) {
                event = parseResult as Record<string, unknown>;
            } else {
                console.error(`[CK3RAVEN] Corrupted journal line ${lineNumber} in ${filePath}: not an object`);
            }

            results.push({
                file: filePath,
                lineNumber,
                line,
                event,
                matchContext: createMatchContext(line, queryLower)
            });
        }
    }

    rl.close();
    return results;
}

/**
 * Create a context snippet around the match
 */
function createMatchContext(line: string, queryLower: string): string {
    const lineLower = line.toLowerCase();
    const index = lineLower.indexOf(queryLower);

    if (index < 0) return line.slice(0, 100);

    // Get context around match
    const start = Math.max(0, index - 30);
    const end = Math.min(line.length, index + queryLower.length + 30);

    let context = line.slice(start, end);
    if (start > 0) context = '...' + context;
    if (end < line.length) context = context + '...';

    return context;
}

/**
 * Register search command
 */
export function registerSearchCommand(
    context: vscode.ExtensionContext,
    getJournalFolder: () => vscode.Uri | undefined
): void {
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'ck3raven.chat.searchJournal',
            async () => {
                const query = await vscode.window.showInputBox({
                    prompt: 'Search journal entries',
                    placeHolder: 'Enter search term'
                });

                if (!query) return;

                const folder = getJournalFolder();
                const results = await searchJournals(folder, query, { maxResults: 50 });

                if (results.length === 0) {
                    vscode.window.showInformationMessage(`No results for "${query}"`);
                    return;
                }

                // Show results in quick pick
                const items = results.map(r => ({
                    label: r.matchContext,
                    description: `Line ${r.lineNumber}`,
                    detail: path.basename(r.file),
                    result: r
                }));

                const selection = await vscode.window.showQuickPick(items, {
                    placeHolder: `${results.length} results for "${query}"`
                });

                if (selection) {
                    // Open file at line
                    const doc = await vscode.workspace.openTextDocument(selection.result.file);
                    await vscode.window.showTextDocument(doc, {
                        selection: new vscode.Range(
                            selection.result.lineNumber - 1, 0,
                            selection.result.lineNumber - 1, 0
                        )
                    });
                }
            }
        )
    );
}
