/**
 * Linting Provider - Real-time syntax validation using ck3raven parser
 */

import * as vscode from 'vscode';
import { PythonBridge } from '../bridge/pythonBridge';
import { Logger } from '../utils/logger';

export interface LintError {
    line: number;
    column: number;
    endLine?: number;
    endColumn?: number;
    message: string;
    severity: 'error' | 'warning' | 'info' | 'hint';
    code?: string;
    source?: string;
}

export interface LintResult {
    file: string;
    errors: LintError[];
    parseTime?: number;
}

export class LintingProvider implements vscode.Disposable {
    private disposables: vscode.Disposable[] = [];
    private pendingLints: Map<string, NodeJS.Timeout> = new Map();

    constructor(
        private readonly pythonBridge: PythonBridge,
        private readonly diagnosticCollection: vscode.DiagnosticCollection,
        private readonly logger: Logger
    ) {}

    /**
     * Lint a document and update diagnostics
     */
    async lintDocument(document: vscode.TextDocument): Promise<void> {
        if (document.languageId !== 'paradox-script') {
            return;
        }

        // Cancel any pending lint for this document
        const pending = this.pendingLints.get(document.uri.toString());
        if (pending) {
            clearTimeout(pending);
            this.pendingLints.delete(document.uri.toString());
        }

        try {
            const content = document.getText();
            const filename = document.fileName;

            // Call Python bridge to parse and validate
            const result = await this.pythonBridge.call('lint_file', {
                content,
                filename,
                check_references: true
            });

            // Convert errors to diagnostics
            const diagnostics = this.convertToDiagnostics(result.errors || []);
            this.diagnosticCollection.set(document.uri, diagnostics);

            this.logger.debug(`Linted ${filename}: ${diagnostics.length} issues`);

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
     * Convert lint errors to VS Code diagnostics
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
     * Quick syntax check (no reference validation)
     */
    async quickCheck(content: string, filename?: string): Promise<LintError[]> {
        try {
            const result = await this.pythonBridge.call('parse_content', {
                content,
                filename: filename || 'inline.txt'
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

    dispose(): void {
        for (const [, timeout] of this.pendingLints) {
            clearTimeout(timeout);
        }
        this.pendingLints.clear();

        for (const disposable of this.disposables) {
            disposable.dispose();
        }
        this.disposables = [];
    }
}
