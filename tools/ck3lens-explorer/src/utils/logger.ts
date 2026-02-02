/**
 * Logger utility for CK3 Lens
 */

import * as vscode from 'vscode';

export type LogLevel = 'off' | 'error' | 'info' | 'debug';

export class Logger implements vscode.Disposable {
    private level: LogLevel;
    private readonly disposables: vscode.Disposable[] = [];

    constructor(private readonly outputChannel: vscode.OutputChannel) {
        this.level = vscode.workspace.getConfiguration('ck3lens').get<LogLevel>('traceLevel') || 'info';
        
        // Watch for configuration changes - MUST be disposed to prevent listener leaks
        const configListener = vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('ck3lens.traceLevel')) {
                this.level = vscode.workspace.getConfiguration('ck3lens').get<LogLevel>('traceLevel') || 'info';
            }
        });
        this.disposables.push(configListener);
    }

    private shouldLog(level: LogLevel): boolean {
        const levels: LogLevel[] = ['off', 'error', 'info', 'debug'];
        return levels.indexOf(level) <= levels.indexOf(this.level);
    }

    private formatMessage(level: string, message: string): string {
        const timestamp = new Date().toISOString();
        return `[${timestamp}] [${level.toUpperCase()}] ${message}`;
    }

    error(message: string, error?: any): void {
        if (this.shouldLog('error')) {
            let fullMessage = message;
            if (error) {
                if (error instanceof Error) {
                    fullMessage += `: ${error.message}`;
                    if (error.stack) {
                        fullMessage += `\n${error.stack}`;
                    }
                } else {
                    fullMessage += `: ${JSON.stringify(error)}`;
                }
            }
            this.outputChannel.appendLine(this.formatMessage('error', fullMessage));
        }
    }

    info(message: string): void {
        if (this.shouldLog('info')) {
            this.outputChannel.appendLine(this.formatMessage('info', message));
        }
    }

    warn(message: string): void {
        if (this.shouldLog('info')) {  // warn uses info level threshold
            this.outputChannel.appendLine(this.formatMessage('warn', message));
        }
    }

    debug(message: string): void {
        if (this.shouldLog('debug')) {
            this.outputChannel.appendLine(this.formatMessage('debug', message));
        }
    }

    show(): void {
        this.outputChannel.show();
    }

    dispose(): void {
        for (const disposable of this.disposables) {
            disposable.dispose();
        }
        this.disposables.length = 0;
    }
}
