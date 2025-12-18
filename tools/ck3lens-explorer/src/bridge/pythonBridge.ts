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
        const pythonPath = config.get<string>('pythonPath') || 'python';
        let ck3ravenPath = config.get<string>('ck3ravenPath') || '';

        // Auto-detect ck3raven path if not configured
        if (!ck3ravenPath) {
            // Try to find it relative to the extension
            const extensionPath = vscode.extensions.getExtension('ck3-modding.ck3lens-explorer')?.extensionPath;
            if (extensionPath) {
                // Extension is in tools/ck3lens-explorer, ck3raven is in parent
                ck3ravenPath = path.resolve(extensionPath, '..', '..');
            } else {
                // Fallback to workspace folder
                const workspaceFolders = vscode.workspace.workspaceFolders;
                if (workspaceFolders) {
                    for (const folder of workspaceFolders) {
                        if (folder.uri.fsPath.includes('ck3raven')) {
                            ck3ravenPath = folder.uri.fsPath;
                            break;
                        }
                    }
                }
            }
        }

        const bridgeScriptPath = path.join(ck3ravenPath, 'tools', 'ck3lens-explorer', 'bridge', 'server.py');

        this.logger.info(`Starting Python bridge: ${pythonPath} ${bridgeScriptPath}`);

        return new Promise((resolve, reject) => {
            try {
                this.process = spawn(pythonPath, [bridgeScriptPath], {
                    cwd: ck3ravenPath,
                    stdio: ['pipe', 'pipe', 'pipe'],
                    env: {
                        ...process.env,
                        PYTHONUNBUFFERED: '1'
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

                // Wait a moment for process to start
                setTimeout(() => {
                    if (this.process && !this.process.killed) {
                        resolve();
                    } else {
                        reject(new Error('Python process failed to start'));
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
        const pythonPath = config.get<string>('pythonPath') || 'python';
        const ck3ravenPath = config.get<string>('ck3ravenPath') || '';

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

    dispose(): void {
        if (this.process && !this.process.killed) {
            this.process.kill();
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
