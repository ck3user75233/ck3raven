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
 * 
 * MIT TOKEN FIX (February 2026):
 * - MIT token is generated once per activation, stored in memory only
 * - Token is passed to MCP server via CK3LENS_MIT_TOKEN env var
 * - NEVER written to disk (agent could read it with read_file and self-init)
 * - Agent cannot read subprocess env vars, so human-in-the-loop is enforced
 * - Re-initialization allowed (token lifetime = process lifetime)
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as crypto from 'crypto';
import { Logger } from '../utils/logger';
import * as os from 'os';
/// =============================================================================
// CANONICAL PATHS
// =============================================================================

/**
 * Get ROOT_REPO path.
 * 
 * Priority:
 * 1. ~/.ck3raven/config/workspace.toml (canonical source - shared with Python)
 * 2. ck3lens.ck3ravenPath VS Code setting (fallback)
 * 3. __dirname computation (dev mode only)
 * 
 * Returns undefined if not found - MCP server won't start.
 */
function getRootRepo(): string | undefined {
    // Priority 1: workspace.toml (canonical - same config as Python MCP server)
    const configPath = path.join(os.homedir(), '.ck3raven', 'config', 'workspace.toml');
    if (fs.existsSync(configPath)) {
        const content = fs.readFileSync(configPath, 'utf8');
        const match = content.match(/^root_repo\s*=\s*"([^"]+)"/m);
        if (match?.[1] && fs.existsSync(path.join(match[1], 'pyproject.toml'))) {
            return match[1];
        }
    }

    // Priority 2: VS Code setting (explicit override)
    const ck3ravenPath = vscode.workspace.getConfiguration('ck3lens').get<string>('ck3ravenPath');
    if (ck3ravenPath && fs.existsSync(path.join(ck3ravenPath, 'pyproject.toml'))) {
        return ck3ravenPath;
    }

    // Priority 3: __dirname computation (dev mode only)
    const devRoot = path.resolve(__dirname, '..', '..', '..', '..');
    if (fs.existsSync(path.join(devRoot, 'pyproject.toml'))) {
        return devRoot;
    }

    return undefined;
}

// Module-level derived paths (computed at load time)
const ROOT_REPO = getRootRepo();
const ROOT_REPO_VALID = ROOT_REPO !== undefined;
const MCP_SERVER_PATH = ROOT_REPO ? path.join(ROOT_REPO, 'tools', 'ck3lens_mcp', 'server.py') : '';
const VENV_PYTHON_WIN = ROOT_REPO ? path.join(ROOT_REPO, '.venv', 'Scripts', 'python.exe') : '';
const VENV_PYTHON_UNIX = ROOT_REPO ? path.join(ROOT_REPO, '.venv', 'bin', 'python') : '';

/** MCP server entry point (relative to ROOT_REPO) */
const MCP_SERVER_REL_PATH = path.join('tools', 'ck3lens_mcp', 'server.py');

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
    private readonly logger: Logger;
    private disposables: vscode.Disposable[] = [];
    
    /** 
     * When true, provideMcpServerDefinitions returns [].
     * Set by shutdown() before dispose to force VS Code to see empty definitions.
     */
    private isShutdown: boolean = false;
    
    /**
     * MIT token - stored in memory only, passed to MCP server via env var.
     * NEVER written to disk (agent could read it with read_file and self-init).
     * Generated once in constructor, returned by getMitToken(), injected as
     * CK3LENS_MIT_TOKEN env var in provideMcpServerDefinitions().
     */
    private readonly mitToken: string;

    constructor(context: vscode.ExtensionContext, logger: Logger) {
        this.logger = logger;
        
        // CRITICAL: Generate fresh instance ID every activation (no caching!)
        this.instanceId = generateInstanceId();
        
        // Generate MIT token — memory only, never on disk.
        // Security model: agent cannot read env vars of the MCP subprocess,
        // and all tools (ck3_exec etc.) are blocked before mode initialization.
        // So the agent must receive this token from the user (human-in-the-loop).
        this.mitToken = crypto.randomBytes(8).toString('hex');
        
        // Clean up legacy token file if it exists (was a security hole)
        const legacyTokenPath = path.join(os.homedir(), '.ck3raven', 'config', 'mit_token.txt');
        try {
            if (fs.existsSync(legacyTokenPath)) {
                fs.unlinkSync(legacyTokenPath);
                this.logger.info('Deleted legacy MIT token file (security fix)');
            }
        } catch { /* ignore */ }
        
        this.logger.info(`MCP activate: instanceId=${this.instanceId}`);
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
     * Get the MIT (Mode Initialization Token) for agent authorization.
     * 
     * Returns the in-memory token that was also passed to the MCP server
     * as CK3LENS_MIT_TOKEN env var at startup. The agent cannot access
     * this token on its own — it must be given by the user via chat.
     */
    getMitToken(): string {
        return this.mitToken;
    }

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

        // Build environment with instance ID and MIT token for isolation
        // MIT token is passed via env var — agent cannot read MCP subprocess env
        // vars before initialization (all tools require _get_world() which needs init)
        const env: Record<string, string | number | null> = {
            CK3LENS_INSTANCE_ID: this.instanceId,
            CK3LENS_MIT_TOKEN: this.mitToken,
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
