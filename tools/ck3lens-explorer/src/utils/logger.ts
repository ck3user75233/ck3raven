/**
 * Logger utility for CK3 Lens
 */

import * as vscode from 'vscode';

export type LogLevel = 'off' | 'error' | 'info' | 'debug';

export class Logger {
    private level: LogLevel;

    constructor(private readonly outputChannel: vscode.OutputChannel) {
        this.level = vscode.workspace.getConfiguration('ck3lens').get<LogLevel>('traceLevel') || 'info';
        
        // Watch for configuration changes
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('ck3lens.traceLevel')) {
                this.level = vscode.workspace.getConfiguration('ck3lens').get<LogLevel>('traceLevel') || 'info';
            }
        });
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

    debug(message: string): void {
        if (this.shouldLog('debug')) {
            this.outputChannel.appendLine(this.formatMessage('debug', message));
        }
    }

    show(): void {
        this.outputChannel.show();
    }
}
