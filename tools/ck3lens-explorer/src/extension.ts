/**
 * CK3 Lens Explorer - VS Code Extension
 * 
 * Game state explorer, conflict resolution, and real-time linting for CK3 mods.
 * Powered by ck3raven parser and database.
 */

import * as vscode from 'vscode';
import { CK3LensSession } from './session';
import { ExplorerViewProvider } from './views/explorerView';
import { ConflictsViewProvider } from './views/conflictsView';
import { SymbolsViewProvider } from './views/symbolsView';
import { LiveModsViewProvider } from './views/liveModsView';
import { AstViewerPanel } from './views/astViewerPanel';
import { StudioPanel } from './views/studioPanel';
import { LintingProvider } from './linting/lintingProvider';
import { DefinitionProvider } from './language/definitionProvider';
import { ReferenceProvider } from './language/referenceProvider';
import { HoverProvider } from './language/hoverProvider';
import { CompletionProvider } from './language/completionProvider';
import { PythonBridge } from './bridge/pythonBridge';
import { LensWidget } from './widget/lensWidget';
import { Logger } from './utils/logger';

// Global extension state
let session: CK3LensSession | undefined;
let pythonBridge: PythonBridge | undefined;
let lensWidget: LensWidget | undefined;
let logger: Logger;
let outputChannel: vscode.OutputChannel;
let diagnosticCollection: vscode.DiagnosticCollection;

/**
 * Extension activation
 */
export async function activate(context: vscode.ExtensionContext): Promise<void> {
    // Initialize logging
    outputChannel = vscode.window.createOutputChannel('CK3 Lens');
    logger = new Logger(outputChannel);
    logger.info('CK3 Lens Explorer activating...');

    // Initialize diagnostic collection for linting
    diagnosticCollection = vscode.languages.createDiagnosticCollection('ck3lens');
    context.subscriptions.push(diagnosticCollection);

    // Initialize Python bridge to ck3raven
    pythonBridge = new PythonBridge(logger);
    context.subscriptions.push(pythonBridge);

    // Initialize session (lazy - will connect when first command is run)
    session = new CK3LensSession(pythonBridge, logger);

    // Register view providers
    const explorerProvider = new ExplorerViewProvider(session, logger);
    const conflictsProvider = new ConflictsViewProvider(session, logger);
    const symbolsProvider = new SymbolsViewProvider(session, logger);
    const liveModsProvider = new LiveModsViewProvider(session, logger);

    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('ck3lens.explorerView', explorerProvider),
        vscode.window.registerTreeDataProvider('ck3lens.conflictsView', conflictsProvider),
        vscode.window.registerTreeDataProvider('ck3lens.symbolsView', symbolsProvider),
        vscode.window.registerTreeDataProvider('ck3lens.liveModsView', liveModsProvider)
    );

    // Initialize the Lens Widget (status bar + panel)
    lensWidget = new LensWidget(context, logger);
    context.subscriptions.push(lensWidget);

    // Connect widget to session state changes
    lensWidget.onStateChange(state => {
        logger.info(`Widget state changed: lens=${state.lensEnabled}, mode=${state.mode}, agent=${state.agent.status}`);
    });

    // Register language features for paradox-script
    const paradoxSelector: vscode.DocumentSelector = { language: 'paradox-script' };

    // Linting provider
    const lintingProvider = new LintingProvider(pythonBridge, diagnosticCollection, logger);
    context.subscriptions.push(lintingProvider);

    // Definition provider (Go to Definition)
    context.subscriptions.push(
        vscode.languages.registerDefinitionProvider(
            paradoxSelector,
            new DefinitionProvider(session, logger)
        )
    );

    // Reference provider (Find All References)
    context.subscriptions.push(
        vscode.languages.registerReferenceProvider(
            paradoxSelector,
            new ReferenceProvider(session, logger)
        )
    );

    // Hover provider (show info on hover)
    context.subscriptions.push(
        vscode.languages.registerHoverProvider(
            paradoxSelector,
            new HoverProvider(session, logger)
        )
    );

    // Completion provider (intellisense)
    context.subscriptions.push(
        vscode.languages.registerCompletionItemProvider(
            paradoxSelector,
            new CompletionProvider(session, logger),
            ':', '_', '.'  // Trigger characters
        )
    );

    // Register commands
    registerCommands(context, explorerProvider, conflictsProvider, symbolsProvider, liveModsProvider, lintingProvider);

    // Register file watchers for real-time linting
    if (vscode.workspace.getConfiguration('ck3lens').get('enableRealTimeLinting', true)) {
        registerFileWatchers(context, lintingProvider);
    }

    logger.info('CK3 Lens Explorer activated successfully');
}

/**
 * Register all extension commands
 */
function registerCommands(
    context: vscode.ExtensionContext,
    explorerProvider: ExplorerViewProvider,
    conflictsProvider: ConflictsViewProvider,
    symbolsProvider: SymbolsViewProvider,
    liveModsProvider: LiveModsViewProvider,
    lintingProvider: LintingProvider
): void {
    // Initialize session
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.initSession', async () => {
            try {
                await session?.initialize();
                vscode.window.showInformationMessage('CK3 Lens session initialized');
                
                // Refresh all views
                explorerProvider.refresh();
                conflictsProvider.refresh();
                symbolsProvider.refresh();
                liveModsProvider.refresh();
            } catch (error) {
                logger.error('Failed to initialize session', error);
                vscode.window.showErrorMessage(`Failed to initialize CK3 Lens: ${error}`);
            }
        })
    );

    // Refresh all views
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.refreshViews', () => {
            explorerProvider.refresh();
            conflictsProvider.refresh();
            symbolsProvider.refresh();
            liveModsProvider.refresh();
        })
    );

    // Validate current file
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.validateFile', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showWarningMessage('No active editor');
                return;
            }
            
            await lintingProvider.lintDocument(editor.document);
            vscode.window.showInformationMessage('File validated');
        })
    );

    // Validate entire workspace
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.validateWorkspace', async () => {
            await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: 'Validating workspace...',
                cancellable: true
            }, async (progress, token) => {
                const files = await vscode.workspace.findFiles('**/*.txt', '**/node_modules/**');
                const total = files.length;
                let processed = 0;

                for (const file of files) {
                    if (token.isCancellationRequested) {
                        break;
                    }

                    const document = await vscode.workspace.openTextDocument(file);
                    await lintingProvider.lintDocument(document);
                    
                    processed++;
                    progress.report({
                        message: `${processed}/${total} files`,
                        increment: (1 / total) * 100
                    });
                }

                vscode.window.showInformationMessage(`Validated ${processed} files`);
            });
        })
    );

    // Search symbols
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.searchSymbols', async () => {
            const query = await vscode.window.showInputBox({
                prompt: 'Search for symbols (traits, events, decisions, etc.)',
                placeHolder: 'e.g., brave, on_death, convert_faith'
            });

            if (query) {
                const results = await session?.searchSymbols(query);
                if (results && results.length > 0) {
                    symbolsProvider.showSearchResults(results);
                } else {
                    vscode.window.showInformationMessage('No symbols found');
                }
            }
        })
    );

    // Show conflicts
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.showConflicts', async () => {
            const folder = await vscode.window.showInputBox({
                prompt: 'Folder to check for conflicts (leave empty for all)',
                placeHolder: 'e.g., common/on_action, common/traits'
            });

            const conflicts = await session?.getConflicts(folder || undefined);
            if (conflicts && conflicts.length > 0) {
                conflictsProvider.showConflicts(conflicts);
            } else {
                vscode.window.showInformationMessage('No conflicts found');
            }
        })
    );

    // Go to definition
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.goToDefinition', async () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                await vscode.commands.executeCommand('editor.action.revealDefinition');
            }
        })
    );

    // Find references
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.findReferences', async () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                await vscode.commands.executeCommand('editor.action.goToReferences');
            }
        })
    );

    // Open in merge editor
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.openInMergeEditor', async (item: any) => {
            // TODO: Implement merge editor webview
            vscode.window.showInformationMessage('Merge editor coming soon...');
        })
    );

    // Build database
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.buildDatabase', async () => {
            await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: 'Rebuilding ck3raven database...',
                cancellable: false
            }, async () => {
                try {
                    await pythonBridge?.runScript('build_database.py');
                    vscode.window.showInformationMessage('Database rebuilt successfully');
                    
                    // Re-initialize session
                    await session?.initialize();
                    explorerProvider.refresh();
                } catch (error) {
                    logger.error('Failed to rebuild database', error);
                    vscode.window.showErrorMessage(`Failed to rebuild database: ${error}`);
                }
            });
        })
    );

    // Set playset
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.setPlayset', async () => {
            // TODO: Show playset picker
            vscode.window.showInformationMessage('Playset selection coming soon...');
        })
    );

    // Open AST Viewer
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.openAstViewer', async (fileUri?: vscode.Uri, modSource?: string) => {
            // If no URI provided, use the current editor
            let uri = fileUri;
            let source = modSource;
            
            if (!uri) {
                const editor = vscode.window.activeTextEditor;
                if (editor && editor.document.languageId === 'paradox-script') {
                    uri = editor.document.uri;
                } else {
                    // Prompt user to select a file from the explorer
                    vscode.window.showWarningMessage('Open a Paradox script file or select from the Explorer');
                    return;
                }
            }
            
            // Extract filename from path
            const relpath = uri.fsPath.replace(/\\/g, '/');
            const filename = relpath.split('/').pop() || 'unknown';
            
            // Create or reveal AST viewer panel
            AstViewerPanel.createOrShow(context.extensionUri, session!, logger, {
                relpath: filename,
                mod: source || 'unknown',
                content: undefined  // Will be loaded from file
            });
        })
    );

    // Register explorer item click to open AST viewer
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.explorerItemClick', async (item: any) => {
            if (item && item.data?.relpath) {
                // Open in AST viewer
                AstViewerPanel.createOrShow(
                    context.extensionUri, 
                    session!, 
                    logger, 
                    {
                        relpath: item.data.relpath,
                        mod: item.data.modName || 'vanilla',
                        content: undefined
                    }
                );
            }
        })
    );

    // Open Studio panel for file creation/editing
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.openStudio', () => {
            StudioPanel.createOrShow(context.extensionUri, session!, logger);
        })
    );
}

/**
 * Register file watchers for real-time linting
 */
function registerFileWatchers(context: vscode.ExtensionContext, lintingProvider: LintingProvider): void {
    // Watch for document saves
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(async (document) => {
            if (document.languageId === 'paradox-script') {
                if (vscode.workspace.getConfiguration('ck3lens').get('lintOnSave', true)) {
                    await lintingProvider.lintDocument(document);
                }
            }
        })
    );

    // Watch for document changes (with debounce)
    let lintTimeout: NodeJS.Timeout | undefined;
    context.subscriptions.push(
        vscode.workspace.onDidChangeTextDocument((event) => {
            if (event.document.languageId === 'paradox-script') {
                if (lintTimeout) {
                    clearTimeout(lintTimeout);
                }
                
                const delay = vscode.workspace.getConfiguration('ck3lens').get('lintDelay', 500);
                lintTimeout = setTimeout(async () => {
                    await lintingProvider.lintDocument(event.document);
                }, delay);
            }
        })
    );

    // Clear diagnostics when document closes
    context.subscriptions.push(
        vscode.workspace.onDidCloseTextDocument((document) => {
            diagnosticCollection.delete(document.uri);
        })
    );
}

/**
 * Extension deactivation
 */
export function deactivate(): void {
    logger?.info('CK3 Lens Explorer deactivating...');
    session?.dispose();
    pythonBridge?.dispose();
    lensWidget?.dispose();
}
