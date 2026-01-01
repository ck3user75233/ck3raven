/**
 * CK3 Lens Explorer - VS Code Extension
 * 
 * Game state explorer, conflict resolution, and real-time linting for CK3 mods.
 * Powered by ck3raven parser and database.
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { CK3LensSession } from './session';
import { ExplorerViewProvider } from './views/explorerView';
import { ConflictsViewProvider } from './views/conflictsView';
import { LiveModsViewProvider } from './views/liveModsView';
import { PlaysetViewProvider } from './views/playsetView';
import { IssuesViewProvider } from './views/issuesView';
import { AgentViewProvider } from './views/agentView';
// DEPRECATED: RulesView is disabled - mode is now set via MCP ck3_get_mode_instructions()
// import { RulesViewProvider } from './views/rulesView';
import { ContractsViewProvider } from './views/contractsView';
import { AstViewerPanel } from './views/astViewerPanel';
import { StudioPanel } from './views/studioPanel';
import { LintingProvider } from './linting/lintingProvider';
import { DefinitionProvider } from './language/definitionProvider';
import { ReferenceProvider } from './language/referenceProvider';
import { HoverProvider } from './language/hoverProvider';
import { CompletionProvider } from './language/completionProvider';
import { PythonBridge } from './bridge/pythonBridge';
import { LensStatusBar } from './widget/statusBar';
import { Logger } from './utils/logger';
import { SetupWizard, showSetupStatus } from './setup/setupWizard';
import { registerMcpServerProvider, CK3LensMcpServerProvider } from './mcp/mcpServerProvider';
import { DiagnosticsServer } from './ipc/diagnosticsServer';

// Global extension state
let session: CK3LensSession | undefined;
let pythonBridge: PythonBridge | undefined;
let statusBar: LensStatusBar | undefined;
let mcpServerProvider: CK3LensMcpServerProvider | undefined;
let diagnosticsServer: DiagnosticsServer | undefined;
let logger: Logger;
let outputChannel: vscode.OutputChannel;
let diagnosticCollection: vscode.DiagnosticCollection;

/**
 * Clean up stale agent mode files from old instances.
 * Files older than 24 hours are deleted.
 */
function cleanupStaleModeFiles(logger: Logger): void {
    const modeDir = path.join(os.homedir(), '.ck3raven');
    const maxAgeMs = 24 * 60 * 60 * 1000; // 24 hours
    const cutoff = Date.now() - maxAgeMs;
    
    try {
        if (!fs.existsSync(modeDir)) {
            return;
        }
        
        const files = fs.readdirSync(modeDir);
        let deleted = 0;
        let kept = 0;
        
        for (const file of files) {
            if (!file.startsWith('agent_mode_') || !file.endsWith('.json')) {
                continue;
            }
            
            const filePath = path.join(modeDir, file);
            try {
                const stat = fs.statSync(filePath);
                if (stat.mtimeMs < cutoff) {
                    fs.unlinkSync(filePath);
                    deleted++;
                } else {
                    kept++;
                }
            } catch {
                // Ignore individual file errors
            }
        }
        
        if (deleted > 0) {
            logger.info(`Cleaned up ${deleted} stale mode files (kept ${kept})`);
        }
    } catch (err) {
        logger.debug('Failed to clean up stale mode files: ' + (err as Error).message);
    }
}

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

    // Register MCP Server Provider for per-window instance isolation
    // This replaces the static mcp.json approach and allows multiple VS Code windows
    // to have independent MCP server instances
    mcpServerProvider = registerMcpServerProvider(context, logger);
    
    // CRITICAL: Per-instance mode blanking
    // Must happen AFTER mcpServerProvider is created so we have the instance ID
    // Each VS Code window only blanks its own mode file, not affecting other windows
    if (mcpServerProvider) {
        const instanceId = mcpServerProvider.getInstanceId();
        logger.info(`MCP instance ID for this window: ${instanceId}`);
        
        // Blank this instance's mode file
        const sanitizedId = instanceId.replace(/[^a-zA-Z0-9_-]/g, '_');
        const instanceModeFile = path.join(os.homedir(), '.ck3raven', `agent_mode_${sanitizedId}.json`);
        try {
            fs.mkdirSync(path.dirname(instanceModeFile), { recursive: true });
            fs.writeFileSync(instanceModeFile, JSON.stringify({ 
                mode: null, 
                instance_id: instanceId,
                cleared_at: new Date().toISOString() 
            }, null, 2));
            logger.info(`Blanked agent mode for instance ${instanceId}`);
        } catch (err) {
            logger.error('Failed to blank agent mode', err as Error);
        }
        
        // Clean up stale mode files from old instances (older than 24 hours)
        cleanupStaleModeFiles(logger);
    }

    // Initialize Python bridge to ck3raven
    pythonBridge = new PythonBridge(logger);
    context.subscriptions.push(pythonBridge);

    // Initialize session (lazy - will connect when first command is run)
    session = new CK3LensSession(pythonBridge, logger);

    // Register view providers
    const explorerProvider = new ExplorerViewProvider(session, logger);
    const conflictsProvider = new ConflictsViewProvider(session, logger);
    const liveModsProvider = new LiveModsViewProvider(session, logger);
    const playsetProvider = new PlaysetViewProvider(session, logger);
    const issuesProvider = new IssuesViewProvider(session, logger);
    const agentProvider = new AgentViewProvider(context, logger);
    // DEPRECATED: RulesView disabled - mode now controlled via MCP ck3_get_mode_instructions()
    // const rulesProvider = new RulesViewProvider(logger);
    
    // ContractsView: Shows active contracts and operation history
    const contractsProvider = new ContractsViewProvider(logger);

    // Create playset tree view with drag-and-drop support
    const playsetTreeView = vscode.window.createTreeView('ck3lens.playsetView', {
        treeDataProvider: playsetProvider,
        dragAndDropController: playsetProvider,
        canSelectMany: false
    });

    // DEPRECATED: RulesView disabled - mode now controlled via MCP
    // const rulesTreeView = vscode.window.createTreeView('ck3lens.rulesView', {
    //     treeDataProvider: rulesProvider,
    //     manageCheckboxStateManually: true
    // });
    // rulesProvider.registerTreeView(rulesTreeView);

    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('ck3lens.agentView', agentProvider),
        vscode.window.registerTreeDataProvider('ck3lens.explorerView', explorerProvider),
        vscode.window.registerTreeDataProvider('ck3lens.conflictsView', conflictsProvider),
        vscode.window.registerTreeDataProvider('ck3lens.liveModsView', liveModsProvider),
        playsetTreeView,
        vscode.window.registerTreeDataProvider('ck3lens.issuesView', issuesProvider),
        vscode.window.registerTreeDataProvider('ck3lens.contractsView', contractsProvider),
        // rulesTreeView  // DEPRECATED
    );

    // Initialize the Status Bar
    statusBar = new LensStatusBar(context, logger);
    context.subscriptions.push(statusBar);

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
    // NOTE: rulesProvider removed - mode now controlled via MCP ck3_get_mode_instructions()
    registerCommands(context, agentProvider, explorerProvider, conflictsProvider, liveModsProvider, playsetProvider, issuesProvider, lintingProvider, contractsProvider);

    // Register file watchers for real-time linting
    if (vscode.workspace.getConfiguration('ck3lens').get('enableRealTimeLinting', true)) {
        registerFileWatchers(context, lintingProvider);
    }

    // Start the IPC diagnostics server for MCP tool access
    diagnosticsServer = new DiagnosticsServer(logger);
    context.subscriptions.push(diagnosticsServer);
    diagnosticsServer.start().then(() => {
        logger.info(`IPC diagnostics server started on port ${diagnosticsServer?.getPort()}`);
    }).catch(err => {
        logger.error('Failed to start IPC diagnostics server', err);
    });

    logger.info('CK3 Lens Explorer activated successfully');

    // Auto-initialize session on startup if enabled (default: true)
    if (vscode.workspace.getConfiguration('ck3lens').get('autoInitialize', true)) {
        // Delay slightly to let UI finish loading
        setTimeout(async () => {
            try {
                logger.info('Auto-initializing CK3 Lens session...');
                await vscode.commands.executeCommand('ck3lens.initSession');
            } catch (error) {
                logger.error('Auto-initialization failed', error);
                // Don't show error on auto-init failure - user can manually init
            }
        }, 1000);
    }
}

/**
 * Register all extension commands
 */
function registerCommands(
    context: vscode.ExtensionContext,
    agentProvider: AgentViewProvider,
    explorerProvider: ExplorerViewProvider,
    conflictsProvider: ConflictsViewProvider,
    liveModsProvider: LiveModsViewProvider,
    playsetProvider: PlaysetViewProvider,
    issuesProvider: IssuesViewProvider,
    lintingProvider: LintingProvider,
    contractsProvider: ContractsViewProvider
): void {
    // Initialize session
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.initSession', async () => {
            try {
                await session?.initialize();
                
                // Update status bar to show connected
                statusBar?.setPythonBridgeStatus('connected');
                
                // Update agent view - Python Bridge is now connected
                agentProvider.setPythonBridgeStatus('connected');
                
                vscode.window.showInformationMessage('CK3 Lens session initialized');
                
                // Refresh all views
                explorerProvider.refresh();
                conflictsProvider.refresh();
                liveModsProvider.refresh();
                playsetProvider.refresh();
            } catch (error) {
                logger.error('Failed to initialize session', error);
                
                // Update status bar to show disconnected
                statusBar?.setPythonBridgeStatus('disconnected');
                
                // Update agent view - Python Bridge failed
                agentProvider.setPythonBridgeStatus('disconnected');
                
                vscode.window.showErrorMessage(`Failed to initialize CK3 Lens: ${error}`);
            }
        })
    );

    // Refresh all views
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.refreshViews', async () => {
            explorerProvider.refresh();
            conflictsProvider.refresh();
            liveModsProvider.refresh();
            playsetProvider.refresh();
            // Also re-check MCP server status
            await agentProvider.recheckMcpStatus();
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

    // Search symbols (results shown in quick pick)
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.searchSymbols', async () => {
            const query = await vscode.window.showInputBox({
                prompt: 'Search for symbols (traits, events, decisions, etc.)',
                placeHolder: 'e.g., brave, on_death, convert_faith'
            });

            if (query) {
                const results = await session?.searchSymbols(query);
                if (results && results.length > 0) {
                    // Show results in quick pick
                    const items = results.map(r => ({
                        label: r.name,
                        description: `${r.symbolType} (${r.mod})`,
                        detail: r.relpath
                    }));
                    const selected = await vscode.window.showQuickPick(items, {
                        placeHolder: `Found ${results.length} symbols`
                    });
                    if (selected) {
                        vscode.window.showInformationMessage(`Selected: ${selected.label} - ${selected.detail}`);
                    }
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

    // ------------------------------------------
    // Validation Rules Commands - DEPRECATED
    // Mode is now controlled via MCP ck3_get_mode_instructions()
    // These commands are preserved as stubs for backwards compatibility
    // ------------------------------------------
    
    /*
    // Toggle a validation rule on/off
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.rules.toggle', async (item?: { ruleId?: string }) => {
            if (item?.ruleId) {
                await rulesProvider.toggleRule(item.ruleId);
            }
        })
    );

    // Set severity for a validation rule
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.rules.setSeverity', async (item?: { ruleId?: string }) => {
            if (item?.ruleId) {
                await rulesProvider.setSeverity(item.ruleId);
            }
        })
    );

    // Refresh rules view
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.rules.refresh', () => {
            rulesProvider.refresh();
        })
    );

    // Open rules config file
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.rules.openConfig', async () => {
            const configPath = rulesProvider.getConfigPath();
            if (configPath) {
                const uri = vscode.Uri.file(configPath);
                await vscode.window.showTextDocument(uri);
            } else {
                vscode.window.showWarningMessage('Config file not found');
            }
        })
    );

    // Enable CK3 Lens mode rules
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.rules.enableCk3lens', () => {
            rulesProvider.enableCk3lensMode();
        })
    );

    // Enable CK3 Raven Dev mode rules
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.rules.enableCk3ravenDev', () => {
            rulesProvider.enableCk3ravenDevMode();
        })
    );

    // Disable all rules
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.rules.disableAll', () => {
            rulesProvider.disableAllRules();
        })
    );
    */

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

    // ========================================================================
    // Issues View Commands
    // ========================================================================

    // Refresh issues view
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.refreshIssues', () => {
            issuesProvider.loadIssues();
        })
    );

    // Navigate to issue location
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.navigateToIssue', async (filePath: string, line: number) => {
            try {
                const uri = vscode.Uri.file(filePath);
                const doc = await vscode.workspace.openTextDocument(uri);
                const editor = await vscode.window.showTextDocument(doc);
                
                const position = new vscode.Position(Math.max(0, line - 1), 0);
                editor.selection = new vscode.Selection(position, position);
                editor.revealRange(
                    new vscode.Range(position, position),
                    vscode.TextEditorRevealType.InCenter
                );
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to open file: ${filePath}`);
                logger.error('Navigation failed', error);
            }
        })
    );

    // Show conflict detail
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.showConflictDetail', async (conflictUnitId: string) => {
            try {
                if (!session?.isInitialized) {
                    vscode.window.showWarningMessage('CK3 Lens not initialized');
                    return;
                }

                const detail = await session.getConflictDetail(conflictUnitId);
                if (!detail) {
                    vscode.window.showErrorMessage('Conflict not found');
                    return;
                }

                // Show in quick pick with candidates
                const items = detail.candidates.map((c: any) => ({
                    label: c.mod_name,
                    description: c.file_path,
                    detail: c.content_preview?.substring(0, 100) + '...',
                    candidate: c
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    title: `Conflict: ${detail.unit_key}`,
                    placeHolder: 'Select a candidate to view'
                });

                if (selected) {
                    // Navigate to the selected candidate
                    await vscode.commands.executeCommand(
                        'ck3lens.navigateToIssue',
                        selected.candidate.file_path,
                        selected.candidate.line_number || 1
                    );
                }
            } catch (error) {
                logger.error('Show conflict detail failed', error);
            }
        })
    );

    // Playset setup - sends user to chat for guided playset configuration
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.setupPlayset', async () => {
            const prompt = `Help me set up my CK3 active playset.

First, call ck3_list_playsets to show me my available playsets.
Then call ck3_get_active_playset to show the current configuration.

After that, ask me what I'd like to do:
1. Add mods to the active playset
2. Remove mods from the active playset
3. Change the load order
4. Switch to a different playset

Use the appropriate tools (ck3_add_mod_to_playset, ck3_remove_mod_from_playset) based on my response.`;

            // Send the prompt to the chat
            await vscode.commands.executeCommand('workbench.action.chat.open', {
                query: prompt
            });
        })
    );

    // View playsets - quick list of all playsets
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.viewPlaysets', async () => {
            if (!session?.isInitialized) {
                vscode.window.showWarningMessage('CK3 Lens not initialized');
                return;
            }

            try {
                const playsets = await session.listPlaysets();
                
                if (!playsets || playsets.length === 0) {
                    vscode.window.showInformationMessage('No playsets found in database');
                    return;
                }

                const items = playsets.map((p: any) => ({
                    label: p.is_active ? `$(check) ${p.name}` : p.name,
                    description: p.is_active ? 'Active' : '',
                    detail: `ID: ${p.id} | Mods: ${p.mod_count ?? 'unknown'}`,
                    playset: p
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    title: 'Playsets',
                    placeHolder: 'Select a playset to view details or set as active'
                });

                if (selected) {
                    // Ask what to do with the playset
                    const action = await vscode.window.showQuickPick([
                        { label: 'Set as Active', value: 'activate' },
                        { label: 'View in Chat', value: 'view' }
                    ], {
                        title: `Playset: ${selected.playset.name}`,
                        placeHolder: 'What would you like to do?'
                    });

                    if (action?.value === 'view') {
                        await vscode.commands.executeCommand('workbench.action.chat.open', {
                            query: `Show me the details of the playset "${selected.playset.name}" (ID: ${selected.playset.id}). Call ck3_get_active_playset if it's the active one, or explain how to check its contents.`
                        });
                    }
                    // Note: activate would need MCP tool call which requires agent
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to list playsets: ${error}`);
            }
        })
    );

    // Create override patch from context menu
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.createOverridePatch', async (item: any) => {
            if (!session?.isInitialized) {
                vscode.window.showWarningMessage('CK3 Lens not initialized');
                return;
            }

            // Get source path from item
            const sourcePath = item?.issue?.filePath || item?.filePath;
            if (!sourcePath) {
                vscode.window.showErrorMessage('No file path available');
                return;
            }

            // Ask for target mod
            const liveMods = await session.getLiveMods();
            const modItems = liveMods.map(m => ({
                label: m.name,
                description: m.modId,
                modId: m.modId
            }));

            const selectedMod = await vscode.window.showQuickPick(modItems, {
                title: 'Select Target Mod',
                placeHolder: 'Choose which mod to create the patch in'
            });

            if (!selectedMod) {return;}

            // Ask for mode
            const mode = await vscode.window.showQuickPick([
                { label: 'Override Patch', description: 'Creates zzz_msc_[name].txt for partial override', value: 'override_patch' as const },
                { label: 'Full Replace', description: 'Creates [name].txt for complete replacement', value: 'full_replace' as const }
            ], {
                title: 'Select Patch Mode',
                placeHolder: 'How should the patch be created?'
            });

            if (!mode) {return;}

            // Create the patch
            const result = await session.createOverridePatch(sourcePath, selectedMod.modId, mode.value);

            if (result.success && result.full_path) {
                const doc = await vscode.workspace.openTextDocument(result.full_path);
                await vscode.window.showTextDocument(doc);
                vscode.window.showInformationMessage(`Created: ${result.created_path}`);
            } else {
                vscode.window.showErrorMessage(`Failed to create patch: ${result.error}`);
            }
        })
    );

    // ========================================================================
    // Setup Wizard Commands
    // ========================================================================

    // Run full setup wizard
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.runSetupWizard', async () => {
            const wizard = new SetupWizard(context, logger);
            await wizard.run();
        })
    );

    // Show setup status / quick diagnostics
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.showSetupStatus', async () => {
            await showSetupStatus(context, logger);
        })
    );

    // ========================================================================
    // Contracts & Operations Commands
    // ========================================================================

    // Show operation details in output channel
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.contracts.showOperationDetails', async (entry: unknown) => {
            const outputChannel = vscode.window.createOutputChannel('CK3 Lens Operation Details');
            outputChannel.clear();
            outputChannel.appendLine('='.repeat(60));
            outputChannel.appendLine('OPERATION DETAILS');
            outputChannel.appendLine('='.repeat(60));
            outputChannel.appendLine('');
            outputChannel.appendLine(JSON.stringify(entry, null, 2));
            outputChannel.show();
        })
    );

    // View bug reports
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.contracts.viewBugReports', async () => {
            const bugReportsPath = require('path').join(
                process.env.USERPROFILE || process.env.HOME || '',
                '.ck3raven',
                'bug_reports'
            );
            
            const fs = require('fs');
            if (!fs.existsSync(bugReportsPath)) {
                vscode.window.showInformationMessage('No bug reports found.');
                return;
            }

            // Open the bug reports folder
            const uri = vscode.Uri.file(bugReportsPath);
            await vscode.commands.executeCommand('revealFileInOS', uri);
        })
    );

    // Refresh contracts view
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.contracts.refresh', () => {
            contractsProvider.refresh();
        })
    );

    // File a bug report (opens bug report form)
    context.subscriptions.push(
        vscode.commands.registerCommand('ck3lens.contracts.fileBugReport', async () => {
            // Show bug report input form
            const summary = await vscode.window.showInputBox({
                title: 'Bug Report Summary',
                prompt: 'Brief description of the issue',
                placeHolder: 'e.g., Parser fails on nested lists'
            });

            if (!summary) { return; }

            const category = await vscode.window.showQuickPick([
                { label: 'Parser', description: 'CK3 script parsing issues', value: 'parser' },
                { label: 'MCP Tools', description: 'Tool behavior issues', value: 'mcp' },
                { label: 'Extension', description: 'VS Code extension issues', value: 'extension' },
                { label: 'Database', description: 'Database/indexing issues', value: 'database' },
                { label: 'Other', description: 'Other issues', value: 'other' }
            ], {
                title: 'Bug Category',
                placeHolder: 'Select the area affected'
            });

            if (!category) { return; }

            const details = await vscode.window.showInputBox({
                title: 'Additional Details',
                prompt: 'Steps to reproduce, error messages, etc.',
                placeHolder: 'Optional additional context'
            });

            // Create bug report
            const bugReport = {
                id: `bug-${Date.now()}`,
                summary,
                category: category.value,
                details: details || '',
                timestamp: new Date().toISOString(),
                source: 'ck3lens-extension'
            };

            // Save to bug_reports folder
            const fs = require('fs');
            const path = require('path');
            const bugReportsPath = path.join(
                process.env.USERPROFILE || process.env.HOME || '',
                '.ck3raven',
                'bug_reports'
            );

            if (!fs.existsSync(bugReportsPath)) {
                fs.mkdirSync(bugReportsPath, { recursive: true });
            }

            const reportPath = path.join(bugReportsPath, `${bugReport.id}.json`);
            fs.writeFileSync(reportPath, JSON.stringify(bugReport, null, 2));

            vscode.window.showInformationMessage(`Bug report filed: ${bugReport.id}`);
            contractsProvider.refresh();
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
    statusBar?.dispose();
}
