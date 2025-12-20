/**
 * Linting Provider - Real-time syntax validation using ck3raven parser
 * 
 * Features:
 * - Debounced real-time validation as you type
 * - Quick TypeScript validation for immediate feedback
 * - Full Python parser validation for comprehensive checking
 * - Parse error detection with recovery hints
 * - Semantic warnings (style, structure)
 * - Reference validation (when enabled)
 */

import * as vscode from 'vscode';
import { PythonBridge } from '../bridge/pythonBridge';
import { Logger } from '../utils/logger';
import { quickValidate, QuickDiagnostic } from './quickValidator';

export interface LintError {
    line: number;
    column: number;
    endLine?: number;
    endColumn?: number;
    message: string;
    severity: 'error' | 'warning' | 'info' | 'hint';
    code?: string;
    source?: string;
    recoveryHint?: string;
}

export interface LintResult {
    file: string;
    errors: LintError[];
    warnings?: LintError[];
    parseTime?: number;
    stats?: {
        lines: number;
        blocks: number;
    };
}

export class LintingProvider implements vscode.Disposable {
    private disposables: vscode.Disposable[] = [];
    private pendingLints: Map<string, NodeJS.Timeout> = new Map();
    private lastValidContent: Map<string, string> = new Map();
    private validationStatusBar: vscode.StatusBarItem;
    private currentErrorCount: number = 0;
    private currentWarningCount: number = 0;
    
    // Debounce delay in milliseconds (adjustable)
    private readonly debounceDelay: number = 300;

    constructor(
        private readonly pythonBridge: PythonBridge,
        private readonly diagnosticCollection: vscode.DiagnosticCollection,
        private readonly logger: Logger
    ) {
        // Create validation status bar item
        this.validationStatusBar = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Left,
            50
        );
        this.validationStatusBar.command = 'workbench.action.problems.focus';
        this.validationStatusBar.tooltip = 'CK3 Lens Validation Status - Click to show Problems';
        this.updateValidationStatusBar();
        
        // Register document change listener for real-time validation
        this.disposables.push(
            vscode.workspace.onDidChangeTextDocument(e => {
                if (e.document.languageId === 'paradox-script') {
                    this.scheduleLint(e.document);
                }
            })
        );
        
        // Register document open listener
        this.disposables.push(
            vscode.workspace.onDidOpenTextDocument(doc => {
                if (doc.languageId === 'paradox-script') {
                    this.lintDocument(doc);
                }
            })
        );
        
        // Register document close listener to clean up
        this.disposables.push(
            vscode.workspace.onDidCloseTextDocument(doc => {
                this.diagnosticCollection.delete(doc.uri);
                this.pendingLints.delete(doc.uri.toString());
                this.lastValidContent.delete(doc.uri.toString());
            })
        );
        
        // Register active editor change listener to update status bar
        this.disposables.push(
            vscode.window.onDidChangeActiveTextEditor(editor => {
                if (editor && editor.document.languageId === 'paradox-script') {
                    // Get diagnostics for this document
                    const diags = this.diagnosticCollection.get(editor.document.uri);
                    if (diags) {
                        this.currentErrorCount = diags.filter(d => d.severity === vscode.DiagnosticSeverity.Error).length;
                        this.currentWarningCount = diags.filter(d => d.severity === vscode.DiagnosticSeverity.Warning).length;
                    } else {
                        // Trigger lint for this document
                        this.lintDocument(editor.document);
                    }
                }
                this.updateValidationStatusBar();
            })
        );
    }

    /**
     * Schedule a debounced lint for a document
     */
    private scheduleLint(document: vscode.TextDocument): void {
        const uri = document.uri.toString();
        
        // Cancel any pending lint for this document
        const pending = this.pendingLints.get(uri);
        if (pending) {
            clearTimeout(pending);
        }
        
        // Run quick validation immediately (TypeScript-based)
        this.runQuickValidation(document);
        
        // Schedule full lint with Python parser
        const timeout = setTimeout(() => {
            this.pendingLints.delete(uri);
            this.lintDocument(document);
        }, this.debounceDelay);
        
        this.pendingLints.set(uri, timeout);
    }

    /**
     * Run quick TypeScript-based validation for immediate feedback
     */
    private runQuickValidation(document: vscode.TextDocument): void {
        const content = document.getText();
        const result = quickValidate(content);
        
        // Show all quick validation diagnostics (errors, warnings, and hints)
        // These will be replaced when the full Python lint completes
        if (result.diagnostics.length > 0) {
            const quickDiagnostics = result.diagnostics
                .map(d => this.convertQuickDiagnostic(d));
            
            this.diagnosticCollection.set(document.uri, quickDiagnostics);
        }
    }

    /**
     * Convert quick diagnostic to VS Code diagnostic
     */
    private convertQuickDiagnostic(diag: QuickDiagnostic): vscode.Diagnostic {
        const range = new vscode.Range(
            diag.line - 1, 
            diag.column - 1,
            diag.endLine ? diag.endLine - 1 : diag.line - 1,
            diag.endColumn || diag.column + 5
        );
        
        const severity = this.mapSeverity(diag.severity);
        const diagnostic = new vscode.Diagnostic(range, diag.message, severity);
        diagnostic.source = 'CK3 Lens (quick)';
        diagnostic.code = diag.code;
        
        return diagnostic;
    }

    /**
     * Check if a file should be linted based on path and content heuristics
     */
    private shouldLintFile(document: vscode.TextDocument): boolean {
        const filePath = document.fileName.toLowerCase();
        const fileName = filePath.split(/[/\\]/).pop() || '';
        
        // Skip known non-script files by name
        const skipNames = [
            'readme.txt', 'intro.txt', 'changelog.txt', 'credits.txt',
            'description.txt', 'license.txt', 'notes.txt', 'todo.txt',
            'checksum_manifest.txt', 'compound_settings.txt', 'credit_portraits.txt'
        ];
        if (skipNames.includes(fileName)) {
            return false;
        }
        
        // Only lint files in expected CK3 directories
        const ck3Paths = [
            '/common/', '/events/', '/decisions/', '/history/', '/gfx/',
            '/gui/', '/localization/', '/map_data/', '/music/', '/sound/',
            '\\common\\', '\\events\\', '\\decisions\\', '\\history\\', '\\gfx\\',
            '\\gui\\', '\\localization\\', '\\map_data\\', '\\music\\', '\\sound\\'
        ];
        
        // If file is not in a CK3 content path, check content
        const inCK3Path = ck3Paths.some(p => filePath.includes(p));
        if (!inCK3Path) {
            // Check if content looks like CK3 script (has = assignments and {})
            const content = document.getText(new vscode.Range(0, 0, 20, 0));
            const hasAssignments = /^\s*\w+\s*=\s*[{\w"]/m.test(content);
            const hasBraces = content.includes('{');
            if (!hasAssignments && !hasBraces) {
                return false;
            }
        }
        
        return true;
    }

    /**
     * Lint a document and update diagnostics
     */
    async lintDocument(document: vscode.TextDocument): Promise<void> {
        if (document.languageId !== 'paradox-script') {
            return;
        }
        
        // Skip files that don't look like CK3 script
        if (!this.shouldLintFile(document)) {
            this.diagnosticCollection.delete(document.uri);
            return;
        }

        const startTime = Date.now();

        try {
            const content = document.getText();
            const filename = document.fileName;

            // Call Python bridge to parse and validate
            const result = await this.pythonBridge.call('lint_file', {
                content,
                filename,
                check_references: true,
                check_style: true
            });

            // Convert errors to diagnostics
            const diagnostics: vscode.Diagnostic[] = [];
            
            // Add error diagnostics
            for (const error of result.errors || []) {
                const diag = this.createDiagnostic(error, vscode.DiagnosticSeverity.Error);
                diagnostics.push(diag);
            }
            
            // Add warning diagnostics
            for (const warning of result.warnings || []) {
                const severity = this.mapSeverity(warning.severity);
                const diag = this.createDiagnostic(warning, severity);
                diagnostics.push(diag);
            }
            
            this.diagnosticCollection.set(document.uri, diagnostics);
            
            // Track valid content for recovery
            if (result.parse_success) {
                this.lastValidContent.set(document.uri.toString(), content);
            }

            // Update counts and status bar
            this.currentErrorCount = (result.errors || []).length;
            this.currentWarningCount = (result.warnings || []).length;
            this.updateValidationStatusBar();

            const elapsed = Date.now() - startTime;
            this.logger.debug(`Linted ${filename}: ${diagnostics.length} issues (${elapsed}ms)`);

        } catch (error) {
            this.logger.error(`Lint failed for ${document.fileName}`, error);
            
            // Show parse error as diagnostic
            const errorDiagnostic = new vscode.Diagnostic(
                new vscode.Range(0, 0, 0, 1),
                `Parse error: ${error}`,
                vscode.DiagnosticSeverity.Error
            );
            errorDiagnostic.source = 'CK3 Lens';
            this.diagnosticCollection.set(document.uri, [errorDiagnostic]);
        }
    }

    /**
     * Create a VS Code diagnostic from a lint error
     */
    private createDiagnostic(error: LintError, defaultSeverity: vscode.DiagnosticSeverity): vscode.Diagnostic {
        const startLine = Math.max(0, error.line - 1);
        const startCol = Math.max(0, (error.column || 1) - 1);
        const endLine = error.endLine ? error.endLine - 1 : startLine;
        const endCol = error.endColumn || startCol + 10;

        const range = new vscode.Range(startLine, startCol, endLine, endCol);
        
        let message = error.message;
        if (error.recoveryHint) {
            message += `\n💡 ${error.recoveryHint}`;
        }
        
        const diagnostic = new vscode.Diagnostic(range, message, defaultSeverity);
        
        diagnostic.source = 'CK3 Lens';
        if (error.code) {
            diagnostic.code = error.code;
        }

        return diagnostic;
    }

    /**
     * Convert lint errors to VS Code diagnostics (legacy method)
     */
    private convertToDiagnostics(errors: LintError[]): vscode.Diagnostic[] {
        return errors.map(error => {
            const startLine = Math.max(0, error.line - 1);
            const startCol = Math.max(0, (error.column || 1) - 1);
            const endLine = error.endLine ? error.endLine - 1 : startLine;
            const endCol = error.endColumn || startCol + 10;

            const range = new vscode.Range(startLine, startCol, endLine, endCol);
            
            const severity = this.mapSeverity(error.severity);
            const diagnostic = new vscode.Diagnostic(range, error.message, severity);
            
            diagnostic.source = 'CK3 Lens';
            if (error.code) {
                diagnostic.code = error.code;
            }

            return diagnostic;
        });
    }

    /**
     * Map severity string to VS Code DiagnosticSeverity
     */
    private mapSeverity(severity: string): vscode.DiagnosticSeverity {
        switch (severity) {
            case 'error':
                return vscode.DiagnosticSeverity.Error;
            case 'warning':
                return vscode.DiagnosticSeverity.Warning;
            case 'info':
                return vscode.DiagnosticSeverity.Information;
            case 'hint':
                return vscode.DiagnosticSeverity.Hint;
            default:
                return vscode.DiagnosticSeverity.Warning;
        }
    }

    /**
     * Quick syntax check (no reference validation) - returns raw errors
     */
    async quickCheck(content: string, filename?: string): Promise<LintError[]> {
        try {
            const result = await this.pythonBridge.call('parse_content', {
                content,
                filename: filename || 'inline.txt',
                include_warnings: false
            });

            return result.errors || [];
        } catch (error) {
            return [{
                line: 1,
                column: 1,
                message: String(error),
                severity: 'error'
            }];
        }
    }

    /**
     * Get the last valid content for a document (for diff/recovery)
     */
    getLastValidContent(uri: vscode.Uri): string | undefined {
        return this.lastValidContent.get(uri.toString());
    }

    /**
     * Force immediate lint (skipping debounce)
     */
    async forceLint(document: vscode.TextDocument): Promise<void> {
        const uri = document.uri.toString();
        
        // Cancel any pending lint
        const pending = this.pendingLints.get(uri);
        if (pending) {
            clearTimeout(pending);
            this.pendingLints.delete(uri);
        }
        
        await this.lintDocument(document);
    }

    /**
     * Update the validation status bar item
     */
    private updateValidationStatusBar(): void {
        const editor = vscode.window.activeTextEditor;
        
        // Only show for paradox-script files
        if (!editor || editor.document.languageId !== 'paradox-script') {
            this.validationStatusBar.hide();
            return;
        }
        
        if (this.currentErrorCount > 0) {
            this.validationStatusBar.text = `$(error) ${this.currentErrorCount} errors`;
            this.validationStatusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
            this.validationStatusBar.tooltip = `CK3 Lens: ${this.currentErrorCount} syntax errors - Click to view`;
        } else if (this.currentWarningCount > 0) {
            this.validationStatusBar.text = `$(warning) ${this.currentWarningCount} warnings`;
            this.validationStatusBar.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
            this.validationStatusBar.tooltip = `CK3 Lens: ${this.currentWarningCount} warnings - Click to view`;
        } else {
            this.validationStatusBar.text = `$(check) Valid`;
            this.validationStatusBar.backgroundColor = undefined;
            this.validationStatusBar.tooltip = 'CK3 Lens: No syntax issues';
        }
        
        this.validationStatusBar.show();
    }

    dispose(): void {
        for (const [, timeout] of this.pendingLints) {
            clearTimeout(timeout);
        }
        this.pendingLints.clear();
        this.lastValidContent.clear();
        
        this.validationStatusBar.dispose();

        for (const disposable of this.disposables) {
            disposable.dispose();
        }
        this.disposables = [];
    }
}
