/**
 * MCP Server Definition Provider
 * 
 * Dynamically provides the CK3 Lens MCP server to VS Code with per-window instance isolation.
 * Each VS Code window gets a unique instance ID, allowing multiple windows to run independent
 * MCP server instances without conflicts.
 * 
 * This replaces the static mcp.json configuration approach.
 * 
 * ZOMBIE BUG FIX (January 2026):
 * - Instance ID is generated fresh on EVERY activation (no PID-based caching)
 * - shutdown() method clears definitions to [] before dispose
 * - Python server exits on stdin EOF
 * See docs/MCP_SERVER_ARCHITECTURE.md for full lifecycle documentation.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as crypto from 'crypto';
import { Logger } from '../utils/logger';

// =============================================================================
// CANONICAL PATHS (computed once at module load)
// =============================================================================

/**
 * ROOT_REPO: The ck3raven repository root.
 * 
 * This extension lives at tools/ck3lens-explorer/dist/mcp/mcpServerProvider.js
 * So ROOT_REPO is 4 levels up from __dirname.
 * 
 * This is THE path constant. WorldAdapter handles "is X inside ROOT_REPO?"
 */
const ROOT_REPO = path.resolve(__dirname, '..', '..', '..');

/** Python executable in the repo's venv */
const VENV_PYTHON_WIN = path.join(ROOT_REPO, '.venv', 'Scripts', 'python.exe');
const VENV_PYTHON_UNIX = path.join(ROOT_REPO, '.venv', 'bin', 'python');

/** MCP server entry point */
const MCP_SERVER_PATH = path.join(ROOT_REPO, 'tools', 'ck3lens_mcp', 'server.py');

/** Verify ROOT_REPO is valid (has pyproject.toml) */
const ROOT_REPO_VALID = fs.existsSync(path.join(ROOT_REPO, 'pyproject.toml'));

// =============================================================================
// INSTANCE ID GENERATION
// =============================================================================

/**
 * Generates a unique instance ID for this activation.
 * 
 * CRITICAL: This is called on EVERY activation to generate a FRESH ID.
 * We do NOT cache by PID or use globalState - that causes the zombie bug
 * where VS Code sees "same server" after reload and caches the connection.
 */
function generateInstanceId(): string {
    const timestamp = Date.now().toString(36).slice(-4);
    const random = crypto.randomBytes(3).toString('hex');
    return `${timestamp}-${random}`;
}

// =============================================================================
// MCP SERVER PROVIDER
// =============================================================================

/**
 * CK3 Lens MCP Server Definition Provider
 * 
 * Provides VS Code with the MCP server definition, injecting a unique instance ID
 * per VS Code window for proper isolation.
 * 
 * LIFECYCLE:
 * 1. Constructor generates fresh instanceId (no caching)
 * 2. provideMcpServerDefinitions() returns server definition with instanceId
 * 3. shutdown() sets isShutdown=true and fires change event (returns [])
 * 4. dispose() cleans up resources
 * 
 * The shutdown() step is CRITICAL for zombie prevention - it tells VS Code
 * that definitions are now empty BEFORE the provider is disposed.
 */
export class CK3LensMcpServerProvider implements vscode.Disposable {
    private readonly _onDidChangeDefinitions = new vscode.EventEmitter<void>();
    readonly onDidChangeMcpServerDefinitions = this._onDidChangeDefinitions.event;

    private readonly instanceId: string;
    private readonly mitToken: string;  // MIT (Mode Initialization Token) for ck3raven-dev authorization
    private readonly logger: Logger;
    private disposables: vscode.Disposable[] = [];
    
    /** 
     * When true, provideMcpServerDefinitions returns [].
     * Set by shutdown() before dispose to force VS Code to see empty definitions.
     */
    private isShutdown: boolean = false;

    constructor(context: vscode.ExtensionContext, logger: Logger) {
        this.logger = logger;
        
        // CRITICAL: Generate fresh instance ID every activation (no caching!)
        this.instanceId = generateInstanceId();
        
        // Generate MIT (Mode Initialization Token) for ck3raven-dev authorization
        // This token is passed to MCP via env var and injected into chat when user clicks "Initialize Dev Mode"
        this.mitToken = crypto.randomBytes(8).toString('hex');
        
        this.logger.info(`MCP activate: instanceId=${this.instanceId}`);
        this.logger.debug(`ROOT_REPO: ${ROOT_REPO}`);
        this.logger.debug(`ROOT_REPO: ${ROOT_REPO}`);
        this.logger.debug(`ROOT_REPO_VALID: ${ROOT_REPO_VALID}`);

        // Watch for configuration changes that might affect the server definition
        this.disposables.push(
            vscode.workspace.onDidChangeConfiguration(e => {
                if (e.affectsConfiguration('ck3lens.pythonPath')) {
                    this.logger.info('Configuration changed, refreshing MCP server definitions');
                    this._onDidChangeDefinitions.fire();
                }
            })
        );
    }

    /**
     * Get the instance ID for this provider.
     */
    getInstanceId(): string {
        return this.instanceId;
    }

    /**
     * Get the MIT (Mode Initialization Token) for ck3raven-dev authorization.
     * This token is single-use - once consumed by the MCP server, user must get a fresh one.
     */
    getMitToken(): string {
        return this.mitToken;
    }

    /**
     * Provides MCP server definitions to VS Code.
    /**
     * Called by VS Code's MCP system when it needs available servers.
     * 
     * CRITICAL: Returns [] if isShutdown is true. This is part of the
     * zombie prevention - on deactivate, we call shutdown() which sets
     * isShutdown=true and fires a change event, causing VS Code to
     * re-query and see empty definitions.
     */
    provideMcpServerDefinitions(
        _token: vscode.CancellationToken
    ): vscode.ProviderResult<vscode.McpStdioServerDefinition[]> {
        // ZOMBIE FIX: Return empty if shutdown was called
        if (this.isShutdown) {
            this.logger.info(`provideDefinitions: [] (shutdown) instanceId=${this.instanceId}`);
            return [];
        }
        
        // Validate ROOT_REPO
        if (!ROOT_REPO_VALID) {
            this.logger.error(`ROOT_REPO invalid: ${ROOT_REPO} (pyproject.toml not found)`);
            return [];
        }

        // Find Python executable
        const pythonPath = this.findPython();
        if (!pythonPath) {
            this.logger.error('No Python found for MCP server');
            return [];
        }

        // Validate server.py exists
        if (!fs.existsSync(MCP_SERVER_PATH)) {
            this.logger.error(`MCP server not found: ${MCP_SERVER_PATH}`);
            return [];
        }

        // Build environment with instance ID for isolation
        const env: Record<string, string | number | null> = {
            CK3LENS_INSTANCE_ID: this.instanceId,
            CK3LENS_MIT_TOKEN: this.mitToken,  // MIT for ck3raven-dev authorization
            PYTHONPATH: `${ROOT_REPO}${path.delimiter}${path.join(ROOT_REPO, 'src')}`,
        };

        // Inject venv into PATH so subprocesses resolve 'python' correctly
        if (pythonPath.includes('.venv')) {
            const venvScriptsDir = path.dirname(pythonPath);
            const venvDir = path.dirname(venvScriptsDir);
            const currentPath = process.env['PATH'] || '';
            env['PATH'] = `${venvScriptsDir}${path.delimiter}${currentPath}`;
            env['VIRTUAL_ENV'] = venvDir;
        }

        // Add config path if configured
        const configPath = vscode.workspace.getConfiguration('ck3lens').get<string>('configPath');
        if (configPath) {
            env['CK3LENS_CONFIG'] = configPath;
        }

        // CRITICAL: Label must be STABLE to prevent zombie servers.
        const serverName = 'CK3 Lens';
        
        this.logger.info(`provideDefinitions: [${serverName}] instanceId=${this.instanceId}`);

        try {
            return [
                new vscode.McpStdioServerDefinition(
                    serverName,
                    pythonPath,
                    ['-m', 'tools.ck3lens_mcp.server'],
                    env,
                    '1.0.0'
                )
            ];
        } catch (error) {
            this.logger.error('Failed to create McpStdioServerDefinition:', error);
            return [];
        }
    }

    /**
     * Find Python executable.
     * Priority: config > venv (Windows) > venv (Unix)
     * NO fallback to bare 'python' (Windows Store stub).
     */
    private findPython(): string | undefined {
        // Priority 1: Extension configuration
        const configuredPython = vscode.workspace.getConfiguration('ck3lens').get<string>('pythonPath');
        if (configuredPython && fs.existsSync(configuredPython)) {
            return configuredPython;
        }

        // Priority 2: Venv in ROOT_REPO
        if (fs.existsSync(VENV_PYTHON_WIN)) {
            return VENV_PYTHON_WIN;
        }
        if (fs.existsSync(VENV_PYTHON_UNIX)) {
            return VENV_PYTHON_UNIX;
        }

        return undefined;
    }

    /**
     * CRITICAL: Called before dispose during deactivation.
     * Sets isShutdown=true and fires change event so VS Code re-queries
     * and sees empty definitions, preventing zombie servers.
     */
    shutdown(): void {
        this.logger.info(`MCP shutdown: instanceId=${this.instanceId}`);
        this.isShutdown = true;
        this._onDidChangeDefinitions.fire();
    }

    dispose(): void {
        this.logger.info(`MCP dispose: instanceId=${this.instanceId}`);
        for (const d of this.disposables) {
            d.dispose();
        }
        this._onDidChangeDefinitions.dispose();
    }
}

// =============================================================================
// REGISTRATION
// =============================================================================

export interface McpProviderRegistration {
    provider: CK3LensMcpServerProvider;
    registration: vscode.Disposable;
}

/**
 * Registers the MCP server provider with VS Code.
 */
export function registerMcpServerProvider(
    context: vscode.ExtensionContext,
    logger: Logger
): McpProviderRegistration | undefined {
    // Check if MCP API is available
    if (!vscode.lm || !vscode.lm.registerMcpServerDefinitionProvider) {
        logger.info('MCP API not available (requires VS Code 1.99+)');
        return undefined;
    }

    const provider = new CK3LensMcpServerProvider(context, logger);
    
    const registration = vscode.lm.registerMcpServerDefinitionProvider(
        'ck3lens-mcp',
        provider
    );

    logger.info(`MCP provider registered: instance=${provider['instanceId']}`);

    return { provider, registration };
}
