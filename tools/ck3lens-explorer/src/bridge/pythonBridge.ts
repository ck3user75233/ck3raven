/**
 * Python Bridge - Communication layer between VS Code extension and ck3raven Python backend
 * 
 * Uses JSON-RPC over stdio to communicate with a Python process running the ck3lens server.
 */

import * as vscode from 'vscode';
import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import { Logger } from '../utils/logger';

interface PendingRequest {
    resolve: (value: any) => void;
    reject: (reason: any) => void;
    timeout: NodeJS.Timeout;
}

export class PythonBridge implements vscode.Disposable {
    private process: ChildProcess | null = null;
    private requestId: number = 0;
    private pendingRequests: Map<number, PendingRequest> = new Map();
    private buffer: string = '';
    private readonly requestTimeout: number = 30000; // 30 seconds

    constructor(private readonly logger: Logger) {}

    /**
     * Ensure Python process is running
     */
    private async ensureProcess(): Promise<void> {
        if (this.process && !this.process.killed) {
            return;
        }

        await this.startProcess();
    }

    /**
     * Start the Python backend process
     */
    private async startProcess(): Promise<void> {
        const config = vscode.workspace.getConfiguration('ck3lens');
        let pythonPath = config.get<string>('pythonPath') || '';
        let ck3ravenPath = config.get<string>('ck3ravenPath') || '';
        
        this.logger.info(`Config pythonPath: '${pythonPath}'`);
        this.logger.info(`Config ck3ravenPath: '${ck3ravenPath}'`);

        // Get the extension's own path (where the bridge script is bundled)
        const extensionPath = vscode.extensions.getExtension('ck3-modding.ck3lens-explorer')?.extensionPath;
        
        // Bridge script is bundled with the extension
        let bridgeScriptPath: string;
        if (extensionPath) {
            bridgeScriptPath = path.join(extensionPath, 'bridge', 'server.py');
        } else {
            // Fallback for development mode - use workspace
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (workspaceFolders) {
                for (const folder of workspaceFolders) {
                    // Try direct path first (ck3lens-explorer folder is opened directly)
                    let tryPath = path.join(folder.uri.fsPath, 'bridge', 'server.py');
                    if (require('fs').existsSync(tryPath)) {
                        bridgeScriptPath = tryPath;
                        // ck3raven root is 2 levels up from tools/ck3lens-explorer
                        ck3ravenPath = path.dirname(path.dirname(folder.uri.fsPath));
                        this.logger.info(`Dev mode: found bridge at ${tryPath}, ck3raven at ${ck3ravenPath}`);
                        break;
                    }
                    // Try nested path (ck3raven repo root is opened)
                    tryPath = path.join(folder.uri.fsPath, 'tools', 'ck3lens-explorer', 'bridge', 'server.py');
                    if (require('fs').existsSync(tryPath)) {
                        bridgeScriptPath = tryPath;
                        ck3ravenPath = folder.uri.fsPath;
                        this.logger.info(`Dev mode: found bridge at ${tryPath}, ck3raven at ${ck3ravenPath}`);
                        break;
                    }
                }
            }
            if (!bridgeScriptPath!) {
                throw new Error('Could not find bridge script - extension path not available');
            }
        }

        // ck3ravenPath is needed for Python imports - try to auto-detect if not configured
        if (!ck3ravenPath) {
            // First check environment variable
            if (process.env.CK3RAVEN_PATH) {
                ck3ravenPath = process.env.CK3RAVEN_PATH;
            } else {
                // Check common locations (no machine-specific paths!)
                const possiblePaths = [
                    path.join(process.env.USERPROFILE || process.env.HOME || '', '.ck3raven', 'ck3raven'),
                    path.join(process.env.HOME || '', 'ck3raven'),
                ];
                for (const p of possiblePaths) {
                    if (require('fs').existsSync(path.join(p, 'src', 'ck3raven'))) {
                        ck3ravenPath = p;
                        break;
                    }
                }
            }
        }

        // Auto-detect Python if not configured - look for venv in ck3raven repo
        // === FIX: First validate any configured path exists ===
        if (pythonPath && path.isAbsolute(pythonPath) && !require('fs').existsSync(pythonPath)) {
            this.logger.warn(`Configured pythonPath does not exist: ${pythonPath}`);
            this.logger.warn(`Falling back to auto-detection...`);
            pythonPath = ''; // Clear to trigger auto-detection
        }
        
        if (!pythonPath) {
            const venvPaths = [
                // Look relative to ck3ravenPath (the repo root)
                path.join(ck3ravenPath, '.venv', 'Scripts', 'python.exe'),  // Windows
                path.join(ck3ravenPath, '.venv', 'bin', 'python'),          // Unix
            ];
            for (const venvPython of venvPaths) {
                if (require('fs').existsSync(venvPython)) {
                    pythonPath = venvPython;
                    this.logger.info(`Auto-detected venv Python: ${pythonPath}`);
                    break;
                }
            }
            // NO FALLBACK TO BARE 'python' - that resolves to Windows Store stub
            if (!pythonPath) {
                this.logger.error('FATAL: No Python found for Python Bridge!');
                this.logger.error(`  ck3ravenPath: ${ck3ravenPath}`);
                this.logger.error(`  Checked venv paths: ${venvPaths.join(', ')}`);
                this.logger.error('Fix: Run the CK3 Lens setup wizard or configure ck3lens.pythonPath');
                throw new Error('No Python interpreter found. Configure ck3lens.pythonPath or run setup wizard.');
            }
        }

        // Validate pythonPath exists (must be absolute at this point)
        if (!path.isAbsolute(pythonPath) || !require('fs').existsSync(pythonPath)) {
            this.logger.error(`FATAL: Python path invalid or missing: ${pythonPath}`);
            throw new Error(`Python interpreter not found: ${pythonPath}`);
        }
        
        this.logger.info(`Starting Python bridge: ${pythonPath} ${bridgeScriptPath}`);
        this.logger.info(`ck3raven path: ${ck3ravenPath || '(not set - bridge may fail imports)'}`);
        this.logger.info(`Extension path: ${extensionPath || '(not found)'}`);

        return new Promise((resolve, reject) => {
            try {
                this.process = spawn(pythonPath, [bridgeScriptPath!], {
                    cwd: ck3ravenPath || path.dirname(bridgeScriptPath!),
                    stdio: ['pipe', 'pipe', 'pipe'],
                    env: {
                        ...process.env,
                        PYTHONUNBUFFERED: '1',
                        PYTHONPATH: ck3ravenPath ? path.join(ck3ravenPath, 'src') : ''
                    }
                });

                this.process.stdout?.on('data', (data: Buffer) => {
                    this.handleStdout(data.toString());
                });

                this.process.stderr?.on('data', (data: Buffer) => {
                    this.logger.error(`Python stderr: ${data.toString()}`);
                });

                this.process.on('error', (error) => {
                    this.logger.error('Python process error', error);
                    reject(error);
                });

                this.process.on('close', (code) => {
                    this.logger.info(`Python process exited with code ${code}`);
                    this.process = null;
                    
                    // Reject all pending requests
                    for (const [id, pending] of this.pendingRequests) {
                        clearTimeout(pending.timeout);
                        pending.reject(new Error('Python process terminated'));
                    }
                    this.pendingRequests.clear();
                });

                // Collect any early stderr for diagnostic purposes
                let stderrBuffer = '';
                const stderrCollector = (data: Buffer) => {
                    stderrBuffer += data.toString();
                };
                this.process.stderr?.on('data', stderrCollector);

                // Wait a moment for process to start
                setTimeout(() => {
                    // Remove temporary collector
                    this.process?.stderr?.removeListener('data', stderrCollector);
                    
                    if (this.process && !this.process.killed) {
                        resolve();
                    } else {
                        const errorDetails = [
                            `Python: ${pythonPath}`,
                            `Script: ${bridgeScriptPath}`,
                            `CK3Raven: ${ck3ravenPath || '(not found)'}`,
                            stderrBuffer ? `Stderr: ${stderrBuffer.slice(0, 500)}` : ''
                        ].filter(Boolean).join('\n');
                        
                        this.logger.error(`Python process failed to start:\n${errorDetails}`);
                        reject(new Error(`Python process failed to start. Check Output > CK3 Lens for details.`));
                    }
                }, 500);

            } catch (error) {
                reject(error);
            }
        });
    }

    /**
     * Handle stdout data from Python process
     */
    private handleStdout(data: string): void {
        this.buffer += data;

        // Process complete JSON-RPC messages (newline-delimited)
        let newlineIndex: number;
        while ((newlineIndex = this.buffer.indexOf('\n')) !== -1) {
            const line = this.buffer.slice(0, newlineIndex).trim();
            this.buffer = this.buffer.slice(newlineIndex + 1);

            if (line) {
                try {
                    const message = JSON.parse(line);
                    this.handleMessage(message);
                } catch (error) {
                    this.logger.debug(`Non-JSON output: ${line}`);
                }
            }
        }
    }

    /**
     * Handle parsed JSON-RPC message
     */
    private handleMessage(message: any): void {
        if (message.id !== undefined && this.pendingRequests.has(message.id)) {
            const pending = this.pendingRequests.get(message.id)!;
            this.pendingRequests.delete(message.id);
            clearTimeout(pending.timeout);

            if (message.error) {
                pending.reject(new Error(message.error.message || JSON.stringify(message.error)));
            } else {
                pending.resolve(message.result);
            }
        } else if (message.method) {
            // Notification from Python (no response expected)
            this.logger.debug(`Notification: ${message.method}`);
        }
    }

    /**
     * Call a method on the Python backend
     */
    async call(method: string, params: any = {}): Promise<any> {
        await this.ensureProcess();

        const id = ++this.requestId;
        const request = {
            jsonrpc: '2.0',
            id,
            method,
            params
        };

        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                this.pendingRequests.delete(id);
                reject(new Error(`Request ${method} timed out after ${this.requestTimeout}ms`));
            }, this.requestTimeout);

            this.pendingRequests.set(id, { resolve, reject, timeout });

            try {
                const message = JSON.stringify(request) + '\n';
                this.process?.stdin?.write(message);
                this.logger.debug(`Sent request: ${method} (id=${id})`);
            } catch (error) {
                this.pendingRequests.delete(id);
                clearTimeout(timeout);
                reject(error);
            }
        });
    }

    /**
     * Run a standalone Python script
     */
    async runScript(scriptName: string, args: string[] = []): Promise<string> {
        const config = vscode.workspace.getConfiguration('ck3lens');
        const ck3ravenPath = config.get<string>('ck3ravenPath') || '';
        
        // Find Python - NO BARE 'python' FALLBACK
        let pythonPath = config.get<string>('pythonPath');
        if (!pythonPath || !require('fs').existsSync(pythonPath)) {
            // Try venv discovery
            const venvPaths = [
                path.join(ck3ravenPath, '.venv', 'Scripts', 'python.exe'),  // Windows
                path.join(ck3ravenPath, '.venv', 'bin', 'python'),          // Unix
            ];
            for (const venvPython of venvPaths) {
                if (require('fs').existsSync(venvPython)) {
                    pythonPath = venvPython;
                    break;
                }
            }
        }
        
        if (!pythonPath || !require('fs').existsSync(pythonPath)) {
            throw new Error('No Python interpreter found. Configure ck3lens.pythonPath or run setup wizard.');
        }

        const scriptPath = path.join(ck3ravenPath, 'scripts', scriptName);

        return new Promise((resolve, reject) => {
            const proc = spawn(pythonPath, [scriptPath, ...args], {
                cwd: ck3ravenPath,
                stdio: ['ignore', 'pipe', 'pipe']
            });

            let stdout = '';
            let stderr = '';

            proc.stdout?.on('data', (data) => {
                stdout += data.toString();
            });

            proc.stderr?.on('data', (data) => {
                stderr += data.toString();
            });

            proc.on('close', (code) => {
                if (code === 0) {
                    resolve(stdout);
                } else {
                    reject(new Error(`Script exited with code ${code}: ${stderr}`));
                }
            });

            proc.on('error', reject);
        });
    }

    async dispose(): Promise<void> {
        if (this.process && !this.process.killed) {
            // Try graceful shutdown first
            try {
                const shutdownPromise = this.call('shutdown', {});
                const timeoutPromise = new Promise((_, reject) => 
                    setTimeout(() => reject(new Error('timeout')), 2000)
                );
                await Promise.race([shutdownPromise, timeoutPromise]);
                this.logger.info('Python bridge shutdown gracefully');
            } catch {
                this.logger.debug('Graceful shutdown failed, forcing kill');
            }
            
            // Force kill if still running
            if (this.process && !this.process.killed) {
                this.process.kill();
            }
            this.process = null;
        }

        // Clear pending requests
        for (const [id, pending] of this.pendingRequests) {
            clearTimeout(pending.timeout);
            pending.reject(new Error('Bridge disposed'));
        }
        this.pendingRequests.clear();
    }
}
