/**
 * MCP Server Definition Provider
 * 
 * Dynamically provides the CK3 Lens MCP server to VS Code with per-window instance isolation.
 * Each VS Code window gets a unique instance ID, allowing multiple windows to run independent
 * MCP server instances without conflicts.
 * 
 * This replaces the static mcp.json configuration approach.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as crypto from 'crypto';
import { Logger } from '../utils/logger';

/**
 * Generates a unique instance ID for this VS Code window.
 * 
 * IMPORTANT: Each VS Code window gets a NEW unique ID, even if opening the same workspace.
 * This allows running multiple agents in parallel with the same workspace.
 * 
 * The ID is stored in globalState with a window-specific key (using process.pid + timestamp)
 * so that reloading the window preserves the ID, but opening a new window generates a new one.
 */
function generateInstanceId(context: vscode.ExtensionContext): string {
    // Use a session-based key that's unique per VS Code window process
    // globalState persists across sessions, so we use a unique key per window
    const windowKey = `ck3lens.windowInstanceId.${process.pid}`;
    
    // Check if this specific window already has an ID (survives reload)
    const existingId = context.globalState.get<string>(windowKey);
    if (existingId) {
        return existingId;
    }

    // Generate a fully random instance ID (no workspace dependency)
    const timestamp = Date.now().toString(36).slice(-4);
    const random = crypto.randomBytes(3).toString('hex');
    const instanceId = `${timestamp}-${random}`;

    // Store with window-specific key
    context.globalState.update(windowKey, instanceId);
    
    // Clean up old window keys (garbage collection)
    // Keep only keys from the last 24 hours
    cleanupOldWindowKeys(context);
    
    return instanceId;
}

/**
 * Clean up old window instance IDs to prevent globalState bloat.
 */
function cleanupOldWindowKeys(context: vscode.ExtensionContext): void {
    const keys = context.globalState.keys();
    const prefix = 'ck3lens.windowInstanceId.';
    const currentPid = process.pid.toString();
    
    for (const key of keys) {
        if (key.startsWith(prefix) && !key.endsWith(currentPid)) {
            // Remove old window keys (from previous VS Code sessions)
            context.globalState.update(key, undefined);
        }
    }
}

/**
 * Finds the Python executable to use for the MCP server.
 * 
 * CRITICAL: Never falls back to bare 'python' - that resolves to Windows Store stub.
 * Returns undefined if no valid Python found, caller must handle gracefully.
 */
function findPythonPath(ck3ravenRoot: string, logger: Logger): string | undefined {
    // Priority 1: Extension configuration
    const config = vscode.workspace.getConfiguration('ck3lens');
    const configuredPython = config.get<string>('pythonPath');
    if (configuredPython && fs.existsSync(configuredPython)) {
        logger.debug(`Using configured Python: ${configuredPython}`);
        return configuredPython;
    }

    // Priority 2: Virtual environment in ck3raven repo (Windows)
    const localVenvWin = path.join(ck3ravenRoot, '.venv', 'Scripts', 'python.exe');
    if (fs.existsSync(localVenvWin)) {
        logger.debug(`Using ck3raven venv Python: ${localVenvWin}`);
        return localVenvWin;
    }

    // Priority 3: Virtual environment in ck3raven repo (Unix)
    const localVenvUnix = path.join(ck3ravenRoot, '.venv', 'bin', 'python');
    if (fs.existsSync(localVenvUnix)) {
        logger.debug(`Using ck3raven venv Python: ${localVenvUnix}`);
        return localVenvUnix;
    }

    // NO FALLBACK TO BARE 'python' - that resolves to Windows Store stub
    logger.error('FATAL: No Python found for MCP server!');
    logger.error(`  Checked configured pythonPath: ${configuredPython || '(not set)'}`);
    logger.error(`  Checked venv (Windows): ${localVenvWin}`);
    logger.error(`  Checked venv (Unix): ${localVenvUnix}`);
    logger.error('Fix: Run the CK3 Lens setup wizard or configure ck3lens.pythonPath');
    return undefined;
}

/**
 * Finds the ck3raven root directory.
 */
function findCk3RavenRoot(logger: Logger): string | undefined {
    // Priority 1: Extension configuration
    const config = vscode.workspace.getConfiguration('ck3lens');
    const configuredPath = config.get<string>('ck3ravenPath');
    if (configuredPath && fs.existsSync(path.join(configuredPath, 'tools', 'ck3lens_mcp', 'server.py'))) {
        logger.debug(`Using configured ck3ravenPath: ${configuredPath}`);
        return configuredPath;
    }

    // Priority 2: Search workspace folders
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (workspaceFolders) {
        for (const folder of workspaceFolders) {
            // Direct match: folder is ck3raven root
            const serverPath = path.join(folder.uri.fsPath, 'tools', 'ck3lens_mcp', 'server.py');
            if (fs.existsSync(serverPath)) {
                logger.debug(`Found ck3raven at workspace folder: ${folder.uri.fsPath}`);
                return folder.uri.fsPath;
            }

            // Subdirectory match: ck3raven is inside folder
            const subPath = path.join(folder.uri.fsPath, 'ck3raven', 'tools', 'ck3lens_mcp', 'server.py');
            if (fs.existsSync(subPath)) {
                logger.debug(`Found ck3raven as subdirectory: ${path.join(folder.uri.fsPath, 'ck3raven')}`);
                return path.join(folder.uri.fsPath, 'ck3raven');
            }
            
            // Dev mode: folder is ck3lens-explorer (tools/ck3lens-explorer), go up 2 levels to ck3raven
            const parentPath = path.dirname(path.dirname(folder.uri.fsPath));
            const parentServerPath = path.join(parentPath, 'tools', 'ck3lens_mcp', 'server.py');
            if (fs.existsSync(parentServerPath)) {
                logger.debug(`Found ck3raven as parent (dev mode): ${parentPath}`);
                return parentPath;
            }
        }
    }
    
    // Priority 3: Check relative to extension path (for development)
    const extensionPath = vscode.extensions.getExtension('ck3-modding.ck3lens-explorer')?.extensionPath;
    if (extensionPath) {
        // If extension is at tools/ck3lens-explorer, go up 2 levels
        const possibleRoot = path.dirname(path.dirname(extensionPath));
        const serverPath = path.join(possibleRoot, 'tools', 'ck3lens_mcp', 'server.py');
        if (fs.existsSync(serverPath)) {
            logger.debug(`Found ck3raven from extension path: ${possibleRoot}`);
            return possibleRoot;
        }
    }
    
    // Priority 4: Check for development extension path (extensionDevelopmentPath)
    // When running "Run Extension" from ck3lens-explorer folder, the extension is there
    // but the ck3raven root is 2 levels up
    if (extensionPath && extensionPath.includes('ck3lens-explorer')) {
        const devRoot = path.dirname(path.dirname(extensionPath));
        const devServerPath = path.join(devRoot, 'tools', 'ck3lens_mcp', 'server.py');
        if (fs.existsSync(devServerPath)) {
            logger.debug(`Found ck3raven from dev extension path: ${devRoot}`);
            return devRoot;
        }
    }

    logger.info('Could not find ck3raven root directory');
    return undefined;
}

/**
 * CK3 Lens MCP Server Definition Provider
 * 
 * Provides VS Code with the MCP server definition, injecting a unique instance ID
 * per VS Code window for proper isolation.
 */
export class CK3LensMcpServerProvider implements vscode.Disposable {
    private readonly _onDidChangeDefinitions = new vscode.EventEmitter<void>();
    readonly onDidChangeMcpServerDefinitions = this._onDidChangeDefinitions.event;

    private readonly instanceId: string;
    private readonly logger: Logger;
    private readonly context: vscode.ExtensionContext;
    private disposables: vscode.Disposable[] = [];

    constructor(context: vscode.ExtensionContext, logger: Logger) {
        this.context = context;
        this.logger = logger;
        this.instanceId = generateInstanceId(context);
        
        this.logger.info(`MCP Server Provider initialized with instance ID: ${this.instanceId}`);

        // Watch for configuration changes that might affect the server definition
        this.disposables.push(
            vscode.workspace.onDidChangeConfiguration(e => {
                if (e.affectsConfiguration('ck3lens.pythonPath') || 
                    e.affectsConfiguration('ck3lens.ck3ravenPath')) {
                    this.logger.info('Configuration changed, refreshing MCP server definitions');
                    this._onDidChangeDefinitions.fire();
                }
            })
        );
    }

    /**
     * Provides MCP server definitions to VS Code.
     * Called by VS Code's MCP system when it needs available servers.
     */
    provideMcpServerDefinitions(
        _token: vscode.CancellationToken
    ): vscode.ProviderResult<vscode.McpStdioServerDefinition[]> {
        const ck3ravenRoot = findCk3RavenRoot(this.logger);
        if (!ck3ravenRoot) {
            this.logger.info('Cannot provide MCP server: ck3raven root not found');
            return [];
        }

        const pythonPath = findPythonPath(ck3ravenRoot, this.logger);
        if (!pythonPath) {
            this.logger.info('Cannot provide MCP server: Python not found');
            return [];
        }

        const serverPath = path.join(ck3ravenRoot, 'tools', 'ck3lens_mcp', 'server.py');
        if (!fs.existsSync(serverPath)) {
            this.logger.info(`Cannot provide MCP server: server.py not found at ${serverPath}`);
            return [];
        }

        // Build environment with instance ID for isolation
        const env: Record<string, string | number | null> = {
            CK3LENS_INSTANCE_ID: this.instanceId,
            // Ensure Python can find ck3raven modules
            PYTHONPATH: path.join(ck3ravenRoot, 'src'),
        };

        // CRITICAL: Inject venv Scripts dir into PATH so subprocesses resolve 'python' correctly
        // This prevents Windows Store Python stub from being used by child processes
        if (pythonPath.includes('.venv')) {
            const venvScriptsDir = path.dirname(pythonPath);  // .venv/Scripts or .venv/bin
            const venvDir = path.dirname(venvScriptsDir);     // .venv
            const currentPath = process.env['PATH'] || '';
            env['PATH'] = `${venvScriptsDir}${path.delimiter}${currentPath}`;
            env['VIRTUAL_ENV'] = venvDir;
            this.logger.debug(`Injected venv into PATH: ${venvScriptsDir}`);
        }

        // Add ck3lens config path if configured
        const configPath = vscode.workspace.getConfiguration('ck3lens').get<string>('configPath');
        if (configPath) {
            env['CK3LENS_CONFIG'] = configPath;
        }

        const serverName = `CK3 Lens (${this.instanceId})`;
        
        this.logger.info(`Providing MCP server: ${serverName}`);
        this.logger.debug(`  Python: ${pythonPath}`);
        this.logger.debug(`  Server: ${serverPath}`);
        this.logger.debug(`  Instance ID: ${this.instanceId}`);
        this.logger.debug(`  CK3RAVEN_ROOT: ${ck3ravenRoot}`);

        // McpStdioServerDefinition constructor: (label, command, args?, env?, version?)
        // NOTE: There is no cwd parameter - server must handle paths internally
        try {
            return [
                new vscode.McpStdioServerDefinition(
                    serverName,           // label
                    pythonPath,           // command
                    [serverPath],         // args
                    env,                  // env
                    '1.0.0'               // version
                )
            ];
        } catch (error) {
            this.logger.error('Failed to create McpStdioServerDefinition:', error);
            return [];
        }
    }

    /**
     * Gets the instance ID for this VS Code window.
     * Useful for other parts of the extension that need to know their identity.
     */
    getInstanceId(): string {
        return this.instanceId;
    }

    dispose(): void {
        this._onDidChangeDefinitions.dispose();
        this.disposables.forEach(d => d.dispose());
    }
}

/**
 * Result of registering the MCP server provider.
 * Both disposables must be disposed on deactivate for clean reload.
 */
export interface McpProviderRegistration {
    provider: CK3LensMcpServerProvider;
    registration: vscode.Disposable;
}

/**
 * Registers the MCP server provider with VS Code.
 * 
 * Note: As of VS Code 1.96, McpServerDefinitionProvider is a proposed API.
 * The extension must declare "mcpServerDefinitionProvider" in enabledApiProposals.
 * 
 * CRITICAL: This is REQUIRED for per-instance isolation. Without it, all VS Code
 * windows share a single MCP server and mode state gets corrupted across windows.
 * We do NOT fall back to static mcp.json - that breaks the architecture.
 * 
 * Returns both provider and registration so caller can dispose them explicitly
 * during deactivate() - this ensures clean disposal on window reload.
 */
export function registerMcpServerProvider(
    context: vscode.ExtensionContext,
    logger: Logger
): McpProviderRegistration | undefined {
    // Check if the API is available - REQUIRED, not optional
    if (!vscode.lm || typeof vscode.lm.registerMcpServerDefinitionProvider !== 'function') {
        const errorMsg = 'CRITICAL: MCP Server Definition Provider API not available. ' +
            'This requires VS Code 1.96+ with mcpServerDefinitionProvider proposed API. ' +
            'Without this, per-instance isolation is broken and mode state corrupts across windows. ' +
            'Delete any static mcp.json and ensure VS Code is updated.';
        logger.error(errorMsg);
        
        // Show prominent error to user
        vscode.window.showErrorMessage(
            'CK3 Lens: MCP per-instance isolation unavailable. ' +
            'Requires VS Code 1.96+. See Output panel for details.',
            'Show Output'
        ).then(selection => {
            if (selection === 'Show Output') {
                logger.show();
            }
        });
        
        // Return undefined but DO NOT silently fall back to static mcp.json
        return undefined;
    }

    try {
        const provider = new CK3LensMcpServerProvider(context, logger);
        
        const registration = vscode.lm.registerMcpServerDefinitionProvider(
            'ck3lens',  // provider ID matching package.json contribution
            provider
        );
        
        // Also add to subscriptions as backup, but caller should dispose explicitly
        context.subscriptions.push(registration);
        context.subscriptions.push(provider);
        
        logger.info('MCP Server Definition Provider registered successfully');
        logger.info(`Per-instance isolation enabled with instance ID: ${provider.getInstanceId()}`);
        
        // Return both so caller can dispose explicitly on deactivate
        return { provider, registration };
    } catch (error) {
        logger.error('Failed to register MCP Server Definition Provider:', error);
        vscode.window.showErrorMessage(
            'CK3 Lens: Failed to register MCP server provider. Per-instance isolation unavailable.',
            'Show Output'
        ).then(selection => {
            if (selection === 'Show Output') {
                logger.show();
            }
        });
        return undefined;
    }
}
