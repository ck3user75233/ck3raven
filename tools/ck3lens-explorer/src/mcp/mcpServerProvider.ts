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
 */
function findPythonPath(ck3ravenRoot: string, logger: Logger): string | undefined {
    // Priority 1: Extension configuration
    const config = vscode.workspace.getConfiguration('ck3lens');
    const configuredPython = config.get<string>('pythonPath');
    if (configuredPython && fs.existsSync(configuredPython)) {
        logger.debug(`Using configured Python: ${configuredPython}`);
        return configuredPython;
    }

    // Priority 2: Virtual environment in ck3raven repo
    const localVenv = path.join(ck3ravenRoot, '.venv', 'Scripts', 'python.exe');
    if (fs.existsSync(localVenv)) {
        logger.debug(`Using ck3raven venv Python: ${localVenv}`);
        return localVenv;
    }

    // Priority 3: System Python
    logger.debug('Falling back to system python');
    return 'python';
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

        // Use McpStdioServerDefinition if available (VS Code 1.96+)
        // Falls back gracefully if the API isn't available
        try {
            return [
                new vscode.McpStdioServerDefinition(
                    serverName,           // label
                    pythonPath,           // command
                    [serverPath],         // args
                    env,                  // environment variables
                    '1.0.0'              // version
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
 * Registers the MCP server provider with VS Code.
 * 
 * Note: As of VS Code 1.96, McpServerDefinitionProvider is a proposed API.
 * The extension must declare "mcpServerDefinitionProvider" in enabledApiProposals.
 */
export function registerMcpServerProvider(
    context: vscode.ExtensionContext,
    logger: Logger
): CK3LensMcpServerProvider | undefined {
    // Check if the API is available
    if (!vscode.lm || typeof vscode.lm.registerMcpServerDefinitionProvider !== 'function') {
        logger.info('MCP Server Definition Provider API not available (requires VS Code 1.96+)');
        logger.info('Falling back to static mcp.json configuration');
        return undefined;
    }

    try {
        const provider = new CK3LensMcpServerProvider(context, logger);
        
        const disposable = vscode.lm.registerMcpServerDefinitionProvider(
            'ck3lens',  // provider ID matching package.json contribution
            provider
        );
        
        context.subscriptions.push(disposable);
        context.subscriptions.push(provider);
        
        logger.info('MCP Server Definition Provider registered successfully');
        return provider;
    } catch (error) {
        logger.error('Failed to register MCP Server Definition Provider:', error);
        return undefined;
    }
}
