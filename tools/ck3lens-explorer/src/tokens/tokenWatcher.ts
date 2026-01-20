/**
 * Token Watcher - Phase 1.5C Token Approval UX
 * 
 * Watches artifacts/tokens_proposed/ for new token proposals.
 * Shows notification with "Mint Token" button that opens the JSON file.
 * 
 * Flow:
 * 1. Agent proposes token → artifacts/tokens_proposed/<id>.token.json
 * 2. Watcher detects new file → shows notification
 * 3. User clicks "Mint Token" → opens JSON in editor
 * 4. User runs "CK3 Lens: Approve Token" command → moves to policy/tokens/
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export interface TokenData {
    schema_version: string;
    token_type: 'NST' | 'LXE';
    token_id: string;
    contract_id: string;
    created_at: string;
    expires_at: string;
    status: 'proposed' | 'approved' | 'rejected' | 'expired';
    justification: string;
    scope: {
        root_category: string;
        target_paths: string[];
        symbol_names?: string[];
        rule_codes?: string[];
        max_violations?: number;
    };
    signature: string;
}

export class TokenWatcher implements vscode.Disposable {
    private watcher: vscode.FileSystemWatcher | undefined;
    private disposables: vscode.Disposable[] = [];
    private repoRoot: string;
    private proposedDir: string;
    private approvedDir: string;
    private outputChannel: vscode.OutputChannel;
    private pythonCommand: string;

    constructor(
        repoRoot: string,
        outputChannel: vscode.OutputChannel,
        pythonCommand: string = 'python'
    ) {
        this.repoRoot = repoRoot;
        this.proposedDir = path.join(repoRoot, 'artifacts', 'tokens_proposed');
        this.approvedDir = path.join(repoRoot, 'policy', 'tokens');
        this.outputChannel = outputChannel;
        this.pythonCommand = pythonCommand;
    }

    /**
     * Start watching for proposed tokens.
     */
    start(): void {
        // Ensure directories exist
        if (!fs.existsSync(this.proposedDir)) {
            this.log('Proposed tokens directory does not exist yet');
            return;
        }

        // Create file system watcher for *.token.json files
        const pattern = new vscode.RelativePattern(
            this.proposedDir,
            '*.token.json'
        );

        this.watcher = vscode.workspace.createFileSystemWatcher(pattern);

        // Watch for new files
        this.watcher.onDidCreate(
            (uri) => this.onTokenCreated(uri),
            null,
            this.disposables
        );

        // Register approve command
        const approveCmd = vscode.commands.registerCommand(
            'ck3lens.approveToken',
            () => this.approveCurrentToken()
        );
        this.disposables.push(approveCmd);

        // Register approve from file command (for context menu)
        const approveFromFileCmd = vscode.commands.registerCommand(
            'ck3lens.approveTokenFile',
            (uri: vscode.Uri) => this.approveTokenFile(uri)
        );
        this.disposables.push(approveFromFileCmd);

        this.log('Token watcher started');
    }

    /**
     * Handle new token file created.
     */
    private async onTokenCreated(uri: vscode.Uri): Promise<void> {
        this.log(`New token proposal: ${uri.fsPath}`);

        try {
            const content = fs.readFileSync(uri.fsPath, 'utf-8');
            const token: TokenData = JSON.parse(content);

            const tokenTypeLabel = token.token_type === 'NST' 
                ? 'New Symbol Token' 
                : 'Lint Exception Token';

            const scopePreview = token.token_type === 'NST'
                ? `${token.scope.symbol_names?.length || 0} symbol(s)`
                : `${token.scope.rule_codes?.length || 0} rule(s)`;

            // Show notification with action buttons
            const result = await vscode.window.showInformationMessage(
                `🪙 ${tokenTypeLabel} proposed: ${scopePreview}`,
                { modal: false },
                'Mint Token',
                'View Details'
            );

            if (result === 'Mint Token') {
                // Open file and immediately approve
                await vscode.window.showTextDocument(uri);
                await this.approveTokenFile(uri);
            } else if (result === 'View Details') {
                // Just open the file for inspection
                await vscode.window.showTextDocument(uri);
            }
        } catch (err) {
            this.log(`Error reading token: ${err}`);
        }
    }

    /**
     * Approve token from currently open file.
     */
    private async approveCurrentToken(): Promise<void> {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('No token file open');
            return;
        }

        const uri = editor.document.uri;
        if (!uri.fsPath.endsWith('.token.json')) {
            vscode.window.showWarningMessage('Current file is not a token file');
            return;
        }

        await this.approveTokenFile(uri);
    }

    /**
     * Approve a specific token file.
     */
    private async approveTokenFile(uri: vscode.Uri): Promise<void> {
        try {
            const content = fs.readFileSync(uri.fsPath, 'utf-8');
            const token: TokenData = JSON.parse(content);

            // Confirm approval
            const confirm = await vscode.window.showWarningMessage(
                `Approve ${token.token_type} token "${token.token_id.slice(0, 8)}..."?\n\n` +
                `Contract: ${token.contract_id}\n` +
                `Justification: ${token.justification}`,
                { modal: true },
                'Approve',
                'Cancel'
            );

            if (confirm !== 'Approve') {
                return;
            }

            // Run Python CLI to approve
            const result = await this.runApproveCommand(token.token_id);

            if (result.success) {
                vscode.window.showInformationMessage(
                    `✅ Token approved: ${token.token_id.slice(0, 8)}...`
                );

                // Close the editor if it was showing the proposed file
                const editor = vscode.window.activeTextEditor;
                if (editor && editor.document.uri.fsPath === uri.fsPath) {
                    await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
                }

                // Open the approved token
                const approvedPath = path.join(
                    this.approvedDir,
                    `${token.token_id}.token.json`
                );
                if (fs.existsSync(approvedPath)) {
                    await vscode.window.showTextDocument(vscode.Uri.file(approvedPath));
                }
            } else {
                vscode.window.showErrorMessage(
                    `Failed to approve token: ${result.error}`
                );
            }
        } catch (err) {
            vscode.window.showErrorMessage(`Error approving token: ${err}`);
        }
    }

    /**
     * Run the Python CLI approve command.
     */
    private async runApproveCommand(tokenId: string): Promise<{ success: boolean; error?: string }> {
        return new Promise((resolve) => {
            const { spawn } = require('child_process');

            const args = [
                '-m', 'tools.compliance.tokens',
                'approve',
                tokenId
            ];

            this.log(`Running: ${this.pythonCommand} ${args.join(' ')}`);

            const proc = spawn(this.pythonCommand, args, {
                cwd: this.repoRoot,
                shell: true,
            });

            let stdout = '';
            let stderr = '';

            proc.stdout.on('data', (data: Buffer) => {
                stdout += data.toString();
            });

            proc.stderr.on('data', (data: Buffer) => {
                stderr += data.toString();
            });

            proc.on('close', (code: number) => {
                this.log(`Approve exit code: ${code}`);
                this.log(`stdout: ${stdout}`);
                if (stderr) {
                    this.log(`stderr: ${stderr}`);
                }

                if (code === 0) {
                    resolve({ success: true });
                } else {
                    resolve({ 
                        success: false, 
                        error: stderr || stdout || `Exit code ${code}` 
                    });
                }
            });

            proc.on('error', (err: Error) => {
                resolve({ success: false, error: err.message });
            });
        });
    }

    private log(message: string): void {
        this.outputChannel.appendLine(`[TokenWatcher] ${message}`);
    }

    dispose(): void {
        this.watcher?.dispose();
        this.disposables.forEach(d => d.dispose());
    }
}
