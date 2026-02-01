/**
 * Diagnostics IPC Server
 * 
 * TCP server that exposes VS Code diagnostics and other IDE APIs to external tools (like MCP server).
 * This allows the MCP server to query VS Code's language server diagnostics, Pylance errors, etc.
 * 
 * Protocol: JSON-RPC over TCP
 * Default port: 9847 (configurable via ck3lens.ipcPort setting)
 */

import * as net from 'net';
import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

interface JsonRpcRequest {
    jsonrpc: '2.0';
    id: number | string;
    method: string;
    params?: any;
}

interface JsonRpcResponse {
    jsonrpc: '2.0';
    id: number | string;
    result?: any;
    error?: {
        code: number;
        message: string;
        data?: any;
    };
}

export class DiagnosticsServer implements vscode.Disposable {
    private server: net.Server | null = null;
    private readonly port: number;
    private readonly host: string = '127.0.0.1';
    private clients: Set<net.Socket> = new Set();

    constructor(private readonly logger: Logger) {
        const config = vscode.workspace.getConfiguration('ck3lens');
        this.port = config.get<number>('ipcPort') || 9847;
    }

    /**
     * Start the TCP server
     */
    public start(): Promise<void> {
        return new Promise(async (resolve, reject) => {
            if (this.server) {
                resolve();
                return;
            }

            // Clean up zombie processes holding our port
            await this.cleanupZombieServer();

            this.server = net.createServer((socket) => {
                this.handleConnection(socket);
            });

            let retried = false;
            this.server.on('error', (err: NodeJS.ErrnoException) => {
                if (err.code === 'EADDRINUSE' && !retried) {
                    retried = true;
                    this.logger.info(`IPC port ${this.port} in use, trying next port...`);
                    this.server?.close();
                    // Retry on next port WITH proper callback
                    this.server?.listen(this.port + 1, this.host, () => {
                        const address = this.server?.address();
                        const actualPort = typeof address === 'object' ? address?.port : this.port + 1;
                        this.logger.info(`Diagnostics IPC server listening on ${this.host}:${actualPort}`);
                        this.writePortFile(actualPort || this.port + 1);
                        resolve();
                    });
                } else if (err.code === 'EADDRINUSE') {
                    // Already retried once, give up - but log clearly
                    this.logger.error(`IPC ports ${this.port} and ${this.port + 1} both in use - ck3_vscode tool will not work`);
                    this.ipcDisabled = true;
                    resolve(); // Don't reject - extension should still work
                } else {
                    this.logger.error('IPC server error', err);
                    resolve(); // Don't reject - extension should still work
                }
            });

            this.server.listen(this.port, this.host, () => {
                const address = this.server?.address();
                const actualPort = typeof address === 'object' ? address?.port : this.port;
                this.logger.info(`Diagnostics IPC server listening on ${this.host}:${actualPort}`);
                
                // Write port to a well-known location so MCP server can find it
                this.writePortFile(actualPort || this.port);
                resolve();
            });
        });
    }

    /**
     * Check for zombie server from crashed VS Code and clean up if found
     */
    private async cleanupZombieServer(): Promise<void> {
        const fs = require('fs');
        const path = require('path');
        const os = require('os');
        const { execSync } = require('child_process');
        
        const portFile = path.join(os.tmpdir(), 'ck3lens_ipc_port');
        
        try {
            if (!fs.existsSync(portFile)) {
                return; // No previous server
            }
            
            const data = JSON.parse(fs.readFileSync(portFile, 'utf8'));
            const { port, pid, timestamp } = data;
            
            // Check if the PID is still alive
            try {
                // On Windows, tasklist returns exit code 0 if process exists
                if (process.platform === 'win32') {
                    execSync(`tasklist /FI "PID eq ${pid}" /NH`, { encoding: 'utf8' });
                    
                    // Check if it's stale (older than 5 minutes without our current PID)
                    const age = Date.now() - timestamp;
                    if (pid !== process.pid && age > 5 * 60 * 1000) {
                        // Old process - try to ping it first
                        const isResponding = await this.pingServer(port);
                        if (!isResponding) {
                            this.logger.warn(`Found zombie IPC server (PID ${pid}, age ${Math.round(age/1000)}s) - cleaning up`);
                            // Delete the stale port file so we can bind
                            fs.unlinkSync(portFile);
                        }
                    }
                }
            } catch {
                // PID doesn't exist - clean up stale file
                this.logger.info(`Cleaning up stale IPC port file from dead process ${pid}`);
                fs.unlinkSync(portFile);
            }
        } catch (err) {
            // Ignore errors - we'll just try to bind anyway
            this.logger.debug(`Zombie cleanup check failed: ${err}`);
        }
    }

    /**
     * Try to ping an existing server to see if it's responsive
     */
    private pingServer(port: number): Promise<boolean> {
        return new Promise((resolve) => {
            const socket = new net.Socket();
            const timeout = setTimeout(() => {
                socket.destroy();
                resolve(false);
            }, 1000);

            socket.connect(port, this.host, () => {
                // Send a ping request
                socket.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'ping' }) + '\n');
            });

            socket.on('data', () => {
                clearTimeout(timeout);
                socket.destroy();
                resolve(true); // Got a response - server is alive
            });

            socket.on('error', () => {
                clearTimeout(timeout);
                socket.destroy();
                resolve(false);
            });
        });
    }

    /**
     * Track if IPC was disabled due to port conflicts
     */
    private ipcDisabled = false;

    /**
     * Check if IPC is available
     */
    public isAvailable(): boolean {
        return this.server !== null && !this.ipcDisabled;
    }

    /**
     * Write port number to a file so MCP server can discover it
     */
    private writePortFile(port: number): void {
        const fs = require('fs');
        const path = require('path');
        const os = require('os');
        
        const portFile = path.join(os.tmpdir(), 'ck3lens_ipc_port');
        try {
            fs.writeFileSync(portFile, JSON.stringify({
                port,
                pid: process.pid,
                timestamp: Date.now()
            }));
            this.logger.debug(`Wrote IPC port file: ${portFile}`);
        } catch (err) {
            this.logger.error('Failed to write port file', err);
        }
    }

    /**
     * Handle a new client connection
     */
    private handleConnection(socket: net.Socket): void {
        this.clients.add(socket);
        this.logger.debug(`IPC client connected from ${socket.remoteAddress}`);

        let buffer = '';

        socket.on('data', async (data) => {
            buffer += data.toString();
            
            // Process complete JSON-RPC messages (newline-delimited)
            let newlineIndex: number;
            while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
                const line = buffer.slice(0, newlineIndex);
                buffer = buffer.slice(newlineIndex + 1);
                
                if (line.trim()) {
                    try {
                        const request: JsonRpcRequest = JSON.parse(line);
                        const response = await this.handleRequest(request);
                        socket.write(JSON.stringify(response) + '\n');
                    } catch (err) {
                        const errorResponse: JsonRpcResponse = {
                            jsonrpc: '2.0',
                            id: 0,
                            error: {
                                code: -32700,
                                message: 'Parse error',
                                data: String(err)
                            }
                        };
                        socket.write(JSON.stringify(errorResponse) + '\n');
                    }
                }
            }
        });

        socket.on('close', () => {
            this.clients.delete(socket);
            this.logger.debug('IPC client disconnected');
        });

        socket.on('error', (err) => {
            this.logger.error('IPC socket error', err);
            this.clients.delete(socket);
        });
    }

    /**
     * Handle a JSON-RPC request
     */
    private async handleRequest(request: JsonRpcRequest): Promise<JsonRpcResponse> {
        const { id, method, params } = request;

        try {
            let result: any;

            switch (method) {
                case 'ping':
                    result = { status: 'ok', timestamp: Date.now() };
                    break;

                case 'getDiagnostics':
                    result = await this.getDiagnostics(params);
                    break;

                case 'getAllDiagnostics':
                    result = await this.getAllDiagnostics(params);
                    break;

                case 'getWorkspaceErrors':
                    result = await this.getWorkspaceErrors(params);
                    break;

                case 'validateFile':
                    result = await this.validateFile(params);
                    break;

                case 'getOpenFiles':
                    result = this.getOpenFiles();
                    break;

                case 'getActiveFile':
                    result = this.getActiveFile();
                    break;

                case 'executeCommand':
                    result = await this.executeCommand(params);
                    break;

                default:
                    return {
                        jsonrpc: '2.0',
                        id,
                        error: {
                            code: -32601,
                            message: `Method not found: ${method}`
                        }
                    };
            }

            return { jsonrpc: '2.0', id, result };
        } catch (err) {
            return {
                jsonrpc: '2.0',
                id,
                error: {
                    code: -32603,
                    message: String(err)
                }
            };
        }
    }

    /**
     * Get diagnostics for a specific file
     */
    private async getDiagnostics(params: { uri?: string; path?: string }): Promise<any> {
        let uri: vscode.Uri;
        
        if (params.uri) {
            uri = vscode.Uri.parse(params.uri);
        } else if (params.path) {
            uri = vscode.Uri.file(params.path);
        } else {
            throw new Error('Either uri or path required');
        }

        const diagnostics = vscode.languages.getDiagnostics(uri);
        
        return {
            uri: uri.toString(),
            path: uri.fsPath,
            diagnostics: diagnostics.map(d => this.serializeDiagnostic(d))
        };
    }

    /**
     * Get all diagnostics across all files
     */
    private async getAllDiagnostics(params?: { 
        severity?: 'error' | 'warning' | 'info' | 'hint';
        source?: string;
        limit?: number;
    }): Promise<any> {
        const allDiagnostics = vscode.languages.getDiagnostics();
        
        let results: Array<{
            uri: string;
            path: string;
            diagnostics: any[];
        }> = [];

        for (const [uri, diagnostics] of allDiagnostics) {
            let filtered = diagnostics;

            // Filter by severity
            if (params?.severity) {
                const severityMap: Record<string, vscode.DiagnosticSeverity> = {
                    'error': vscode.DiagnosticSeverity.Error,
                    'warning': vscode.DiagnosticSeverity.Warning,
                    'info': vscode.DiagnosticSeverity.Information,
                    'hint': vscode.DiagnosticSeverity.Hint
                };
                const targetSeverity = severityMap[params.severity];
                if (targetSeverity !== undefined) {
                    filtered = filtered.filter(d => d.severity === targetSeverity);
                }
            }

            // Filter by source
            if (params?.source) {
                filtered = filtered.filter(d => d.source === params.source);
            }

            if (filtered.length > 0) {
                results.push({
                    uri: uri.toString(),
                    path: uri.fsPath,
                    diagnostics: filtered.map(d => this.serializeDiagnostic(d))
                });
            }
        }

        // Apply limit
        if (params?.limit) {
            results = results.slice(0, params.limit);
        }

        return {
            fileCount: results.length,
            files: results,
            totalDiagnostics: results.reduce((sum, f) => sum + f.diagnostics.length, 0)
        };
    }

    /**
     * Get workspace-wide error summary
     */
    private async getWorkspaceErrors(params?: {
        includeWarnings?: boolean;
        groupBy?: 'file' | 'source' | 'severity';
    }): Promise<any> {
        const allDiagnostics = vscode.languages.getDiagnostics();
        
        let errorCount = 0;
        let warningCount = 0;
        let infoCount = 0;
        const bySource: Record<string, number> = {};
        const byFile: Record<string, { errors: number; warnings: number }> = {};

        for (const [uri, diagnostics] of allDiagnostics) {
            const filePath = uri.fsPath;
            byFile[filePath] = { errors: 0, warnings: 0 };

            for (const d of diagnostics) {
                const source = d.source || 'unknown';
                bySource[source] = (bySource[source] || 0) + 1;

                switch (d.severity) {
                    case vscode.DiagnosticSeverity.Error:
                        errorCount++;
                        byFile[filePath].errors++;
                        break;
                    case vscode.DiagnosticSeverity.Warning:
                        warningCount++;
                        byFile[filePath].warnings++;
                        break;
                    case vscode.DiagnosticSeverity.Information:
                    case vscode.DiagnosticSeverity.Hint:
                        infoCount++;
                        break;
                }
            }
        }

        // Get files with most errors
        const topErrorFiles = Object.entries(byFile)
            .filter(([_, counts]) => counts.errors > 0)
            .sort((a, b) => b[1].errors - a[1].errors)
            .slice(0, 10)
            .map(([path, counts]) => ({ path, ...counts }));

        return {
            summary: {
                errors: errorCount,
                warnings: warningCount,
                info: infoCount,
                filesWithErrors: Object.values(byFile).filter(f => f.errors > 0).length,
                filesWithWarnings: Object.values(byFile).filter(f => f.warnings > 0).length
            },
            bySource,
            topErrorFiles,
            sources: Object.keys(bySource)
        };
    }

    /**
     * Trigger validation for a specific file
     */
    private async validateFile(params: { path: string }): Promise<any> {
        const uri = vscode.Uri.file(params.path);
        
        // Try to open the document to trigger validation
        try {
            const document = await vscode.workspace.openTextDocument(uri);
            
            // Wait a moment for language servers to process
            await new Promise(resolve => setTimeout(resolve, 500));
            
            const diagnostics = vscode.languages.getDiagnostics(uri);
            
            return {
                uri: uri.toString(),
                path: uri.fsPath,
                languageId: document.languageId,
                diagnostics: diagnostics.map(d => this.serializeDiagnostic(d))
            };
        } catch (err) {
            throw new Error(`Failed to open file: ${params.path}`);
        }
    }

    /**
     * Get list of currently open files
     */
    private getOpenFiles(): any {
        const openDocuments = vscode.workspace.textDocuments
            .filter(d => !d.isUntitled && d.uri.scheme === 'file')
            .map(d => ({
                uri: d.uri.toString(),
                path: d.uri.fsPath,
                languageId: d.languageId,
                isDirty: d.isDirty,
                lineCount: d.lineCount
            }));

        return {
            count: openDocuments.length,
            files: openDocuments
        };
    }

    /**
     * Get the currently active file
     */
    private getActiveFile(): any {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            return { active: false };
        }

        const document = editor.document;
        const diagnostics = vscode.languages.getDiagnostics(document.uri);

        return {
            active: true,
            uri: document.uri.toString(),
            path: document.uri.fsPath,
            languageId: document.languageId,
            isDirty: document.isDirty,
            lineCount: document.lineCount,
            selection: {
                line: editor.selection.active.line + 1,
                column: editor.selection.active.character + 1
            },
            diagnostics: diagnostics.map(d => this.serializeDiagnostic(d))
        };
    }

    /**
     * Execute a VS Code command
     */
    private async executeCommand(params: { command: string; args?: any[] }): Promise<any> {
        // Whitelist of allowed commands for security
        const allowedCommands = [
            'ck3lens.validateFile',
            'ck3lens.validateWorkspace',
            'ck3lens.refreshViews',
            'ck3lens.initSession',
            'workbench.action.problems.focus',
            'editor.action.marker.next',
            'editor.action.marker.prev'
        ];

        if (!allowedCommands.includes(params.command)) {
            throw new Error(`Command not allowed: ${params.command}`);
        }

        const result = await vscode.commands.executeCommand(params.command, ...(params.args || []));
        return { executed: true, command: params.command, result };
    }

    /**
     * Serialize a VS Code Diagnostic to a plain object
     */
    private serializeDiagnostic(d: vscode.Diagnostic): any {
        return {
            range: {
                start: { line: d.range.start.line + 1, character: d.range.start.character },
                end: { line: d.range.end.line + 1, character: d.range.end.character }
            },
            message: d.message,
            severity: this.severityToString(d.severity),
            source: d.source,
            code: typeof d.code === 'object' ? d.code.value : d.code,
            relatedInformation: d.relatedInformation?.map(ri => ({
                location: {
                    uri: ri.location.uri.toString(),
                    path: ri.location.uri.fsPath,
                    range: {
                        start: { line: ri.location.range.start.line + 1, character: ri.location.range.start.character },
                        end: { line: ri.location.range.end.line + 1, character: ri.location.range.end.character }
                    }
                },
                message: ri.message
            })),
            tags: d.tags?.map(t => t === vscode.DiagnosticTag.Unnecessary ? 'unnecessary' : 'deprecated')
        };
    }

    /**
     * Convert severity enum to string
     */
    private severityToString(severity: vscode.DiagnosticSeverity): string {
        switch (severity) {
            case vscode.DiagnosticSeverity.Error: return 'error';
            case vscode.DiagnosticSeverity.Warning: return 'warning';
            case vscode.DiagnosticSeverity.Information: return 'info';
            case vscode.DiagnosticSeverity.Hint: return 'hint';
            default: return 'unknown';
        }
    }

    /**
     * Stop the server
     */
    public stop(): void {
        // Close all client connections
        for (const client of this.clients) {
            client.destroy();
        }
        this.clients.clear();

        // Close the server
        if (this.server) {
            this.server.close();
            this.server = null;
        }

        // Clean up port file
        const fs = require('fs');
        const path = require('path');
        const os = require('os');
        const portFile = path.join(os.tmpdir(), 'ck3lens_ipc_port');
        try {
            fs.unlinkSync(portFile);
        } catch {
            // Ignore
        }
    }

    /**
     * Get the current port
     */
    public getPort(): number {
        const address = this.server?.address();
        return typeof address === 'object' ? address?.port || this.port : this.port;
    }

    dispose(): void {
        this.stop();
    }
}
