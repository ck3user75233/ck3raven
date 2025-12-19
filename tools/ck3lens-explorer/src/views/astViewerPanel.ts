/**
 * AST Viewer Panel - Shows file content with AST toggle
 * 
 * Provides side-by-side or toggle view of:
 * - Raw file content (syntax highlighted)
 * - Parsed AST (JSON tree view)
 * - File metadata and provenance info
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

interface AstViewerState {
    fileId?: number;
    relpath: string;
    mod: string;
    content: string;
    ast?: any;
    showAst: boolean;
    errors?: Array<{ line: number; message: string }>;
}

export class AstViewerPanel {
    public static readonly viewType = 'ck3lens.astViewer';
    
    private static currentPanel: AstViewerPanel | undefined;
    
    private readonly panel: vscode.WebviewPanel;
    private readonly session: CK3LensSession;
    private readonly logger: Logger;
    private state: AstViewerState;
    private disposables: vscode.Disposable[] = [];

    public static createOrShow(
        extensionUri: vscode.Uri,
        session: CK3LensSession,
        logger: Logger,
        fileInfo: { relpath: string; mod: string; content?: string; fileId?: number }
    ): AstViewerPanel {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;

        // If we already have a panel, show it
        if (AstViewerPanel.currentPanel) {
            AstViewerPanel.currentPanel.panel.reveal(column);
            AstViewerPanel.currentPanel.loadFile(fileInfo);
            return AstViewerPanel.currentPanel;
        }

        // Create a new panel
        const panel = vscode.window.createWebviewPanel(
            AstViewerPanel.viewType,
            `AST: ${fileInfo.relpath.split('/').pop()}`,
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'media')],
                retainContextWhenHidden: true
            }
        );

        AstViewerPanel.currentPanel = new AstViewerPanel(panel, extensionUri, session, logger, fileInfo);
        return AstViewerPanel.currentPanel;
    }

    private constructor(
        panel: vscode.WebviewPanel,
        private readonly extensionUri: vscode.Uri,
        session: CK3LensSession,
        logger: Logger,
        fileInfo: { relpath: string; mod: string; content?: string; fileId?: number }
    ) {
        this.panel = panel;
        this.session = session;
        this.logger = logger;
        this.state = {
            relpath: fileInfo.relpath,
            mod: fileInfo.mod,
            content: fileInfo.content || '',
            showAst: false,
            fileId: fileInfo.fileId
        };

        // Set the webview's initial html content
        this.update();

        // Listen for when the panel is disposed
        this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

        // Handle messages from the webview
        this.panel.webview.onDidReceiveMessage(
            (message: { command: string; line?: number }) => this.handleMessage(message),
            null,
            this.disposables
        );

        // Load the file content and AST
        this.loadFile(fileInfo);
    }

    public async loadFile(fileInfo: { relpath: string; mod: string; content?: string; fileId?: number }): Promise<void> {
        this.state.relpath = fileInfo.relpath;
        this.state.mod = fileInfo.mod;
        this.state.fileId = fileInfo.fileId;
        
        this.panel.title = `AST: ${fileInfo.relpath.split('/').pop()}`;

        try {
            // Get file from database (includes AST if available)
            const file = await this.session.getFile(fileInfo.relpath, true);
            
            if (file) {
                this.state.content = file.content || '';
                
                // Parse content to get AST
                const parseResult = await this.session.parseContent(this.state.content, fileInfo.relpath);
                this.state.ast = parseResult.ast;
                this.state.errors = parseResult.errors;
            } else if (fileInfo.content) {
                this.state.content = fileInfo.content;
                const parseResult = await this.session.parseContent(this.state.content, fileInfo.relpath);
                this.state.ast = parseResult.ast;
                this.state.errors = parseResult.errors;
            }
        } catch (error) {
            this.logger.error('Failed to load file for AST viewer', error);
            this.state.errors = [{ line: 1, message: String(error) }];
        }

        this.update();
    }

    private handleMessage(message: any): void {
        switch (message.command) {
            case 'toggleView':
                this.state.showAst = !this.state.showAst;
                this.update();
                break;
            
            case 'revealInExplorer':
                this.revealInExplorer();
                break;
            
            case 'copyAst':
                if (this.state.ast) {
                    vscode.env.clipboard.writeText(JSON.stringify(this.state.ast, null, 2));
                    vscode.window.showInformationMessage('AST copied to clipboard');
                }
                break;
            
            case 'goToLine':
                this.goToLine(message.line);
                break;

            case 'openInEditor':
                this.openInEditor();
                break;
        }
    }

    private async revealInExplorer(): Promise<void> {
        // Construct the full file path from database info
        // The file might be in vanilla or a mod directory
        const file = await this.session.getFile(this.state.relpath, false);
        if (!file) {
            vscode.window.showWarningMessage('File not found in database');
            return;
        }

        // Get the actual filesystem path based on mod location
        const config = vscode.workspace.getConfiguration('ck3lens');
        let basePath: string;
        
        if (this.state.mod === 'vanilla') {
            basePath = config.get<string>('vanillaPath') || '';
        } else {
            const modRoot = config.get<string>('modRoot') || '';
            basePath = `${modRoot}/${this.state.mod}`;
        }

        const fullPath = vscode.Uri.file(`${basePath}/${this.state.relpath}`);
        
        try {
            await vscode.commands.executeCommand('revealFileInOS', fullPath);
        } catch (error) {
            this.logger.error('Failed to reveal file in explorer', error);
            vscode.window.showErrorMessage(`Could not reveal file: ${error}`);
        }
    }

    private async openInEditor(): Promise<void> {
        const config = vscode.workspace.getConfiguration('ck3lens');
        let basePath: string;
        
        if (this.state.mod === 'vanilla') {
            basePath = config.get<string>('vanillaPath') || '';
        } else {
            const modRoot = config.get<string>('modRoot') || '';
            basePath = `${modRoot}/${this.state.mod}`;
        }

        const fullPath = vscode.Uri.file(`${basePath}/${this.state.relpath}`);
        
        try {
            const doc = await vscode.workspace.openTextDocument(fullPath);
            await vscode.window.showTextDocument(doc);
        } catch (error) {
            this.logger.error('Failed to open file in editor', error);
            vscode.window.showErrorMessage(`Could not open file: ${error}`);
        }
    }

    private goToLine(line: number): void {
        // If we have the file open in an editor, navigate to the line
        // Otherwise open it and navigate
        this.openInEditor().then(() => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const position = new vscode.Position(line - 1, 0);
                editor.selection = new vscode.Selection(position, position);
                editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
            }
        });
    }

    private update(): void {
        this.panel.webview.html = this.getHtmlContent();
    }

    private getHtmlContent(): string {
        const nonce = this.getNonce();
        
        const syntaxContent = this.escapeHtml(this.state.content);
        const astContent = this.state.ast 
            ? JSON.stringify(this.state.ast, null, 2)
            : 'No AST available - parse failed or content not loaded';
        
        const errorsHtml = this.state.errors && this.state.errors.length > 0
            ? `<div class="errors">
                <h3>⚠️ Parse Errors</h3>
                <ul>
                    ${this.state.errors.map(e => 
                        `<li onclick="goToLine(${e.line})">Line ${e.line}: ${this.escapeHtml(e.message)}</li>`
                    ).join('')}
                </ul>
            </div>`
            : '';

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <title>AST Viewer</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 0;
            margin: 0;
            color: var(--vscode-foreground);
            background: var(--vscode-editor-background);
        }
        .toolbar {
            display: flex;
            gap: 8px;
            padding: 8px 16px;
            background: var(--vscode-titleBar-activeBackground);
            border-bottom: 1px solid var(--vscode-panel-border);
            align-items: center;
            flex-wrap: wrap;
        }
        .toolbar button {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 6px 12px;
            cursor: pointer;
            border-radius: 4px;
        }
        .toolbar button:hover {
            background: var(--vscode-button-hoverBackground);
        }
        .toolbar button.active {
            background: var(--vscode-button-secondaryBackground);
            outline: 2px solid var(--vscode-focusBorder);
        }
        .file-info {
            flex: 1;
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
        }
        .file-info .path { font-weight: bold; }
        .file-info .mod { 
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 8px;
        }
        .content {
            padding: 16px;
            overflow: auto;
            height: calc(100vh - 60px);
        }
        pre {
            margin: 0;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-family: var(--vscode-editor-font-family);
            font-size: var(--vscode-editor-font-size);
            line-height: 1.5;
        }
        .line-numbers {
            display: inline-block;
            width: 50px;
            text-align: right;
            padding-right: 16px;
            color: var(--vscode-editorLineNumber-foreground);
            user-select: none;
        }
        .errors {
            background: var(--vscode-inputValidation-errorBackground);
            border: 1px solid var(--vscode-inputValidation-errorBorder);
            padding: 12px;
            margin-bottom: 16px;
            border-radius: 4px;
        }
        .errors h3 {
            margin: 0 0 8px 0;
            font-size: 14px;
        }
        .errors ul {
            margin: 0;
            padding-left: 20px;
        }
        .errors li {
            cursor: pointer;
            padding: 4px 0;
        }
        .errors li:hover {
            text-decoration: underline;
        }
        .ast-tree {
            font-family: var(--vscode-editor-font-family);
            font-size: 13px;
        }
        .ast-node {
            margin-left: 20px;
        }
        .ast-key {
            color: var(--vscode-symbolIcon-propertyForeground);
        }
        .ast-string {
            color: var(--vscode-symbolIcon-stringForeground);
        }
        .ast-number {
            color: var(--vscode-symbolIcon-numberForeground);
        }
        .ast-line {
            color: var(--vscode-descriptionForeground);
            font-size: 11px;
        }
    </style>
</head>
<body>
    <div class="toolbar">
        <button onclick="toggleView()" class="${this.state.showAst ? '' : 'active'}">📝 Syntax</button>
        <button onclick="toggleView()" class="${this.state.showAst ? 'active' : ''}">🌳 AST</button>
        <button onclick="copyAst()">📋 Copy AST</button>
        <button onclick="openInEditor()">📂 Open in Editor</button>
        <button onclick="revealInExplorer()">🔍 Reveal in Explorer</button>
        <div class="file-info">
            <span class="path">${this.escapeHtml(this.state.relpath)}</span>
            <span class="mod">${this.escapeHtml(this.state.mod)}</span>
        </div>
    </div>
    
    ${errorsHtml}
    
    <div class="content">
        ${this.state.showAst 
            ? `<pre class="ast-tree">${this.formatAstHtml(this.state.ast)}</pre>`
            : `<pre>${this.addLineNumbers(syntaxContent)}</pre>`
        }
    </div>

    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        
        function toggleView() {
            vscode.postMessage({ command: 'toggleView' });
        }
        
        function copyAst() {
            vscode.postMessage({ command: 'copyAst' });
        }
        
        function revealInExplorer() {
            vscode.postMessage({ command: 'revealInExplorer' });
        }
        
        function openInEditor() {
            vscode.postMessage({ command: 'openInEditor' });
        }
        
        function goToLine(line) {
            vscode.postMessage({ command: 'goToLine', line: line });
        }
    </script>
</body>
</html>`;
    }

    private addLineNumbers(content: string): string {
        const lines = content.split('\n');
        return lines.map((line, i) => 
            `<span class="line-numbers">${i + 1}</span>${line}`
        ).join('\n');
    }

    private formatAstHtml(ast: any, indent: number = 0): string {
        if (ast === null || ast === undefined) {
            return '<span class="ast-null">null</span>';
        }
        
        if (typeof ast === 'string') {
            return `<span class="ast-string">"${this.escapeHtml(ast)}"</span>`;
        }
        
        if (typeof ast === 'number') {
            return `<span class="ast-number">${ast}</span>`;
        }
        
        if (typeof ast === 'boolean') {
            return `<span class="ast-boolean">${ast}</span>`;
        }
        
        if (Array.isArray(ast)) {
            if (ast.length === 0) return '[]';
            const items = ast.map(item => 
                '  '.repeat(indent + 1) + this.formatAstHtml(item, indent + 1)
            ).join(',\n');
            return `[\n${items}\n${'  '.repeat(indent)}]`;
        }
        
        if (typeof ast === 'object') {
            const entries = Object.entries(ast);
            if (entries.length === 0) return '{}';
            
            const items = entries.map(([key, value]) => {
                const keyHtml = `<span class="ast-key">"${this.escapeHtml(key)}"</span>`;
                const lineInfo = key === 'line' ? ` <span class="ast-line">(click to navigate)</span>` : '';
                const valueHtml = this.formatAstHtml(value, indent + 1);
                const clickAttr = key === 'line' && typeof value === 'number' 
                    ? ` onclick="goToLine(${value})" style="cursor:pointer"` 
                    : '';
                return `${'  '.repeat(indent + 1)}${keyHtml}: <span${clickAttr}>${valueHtml}</span>${lineInfo}`;
            }).join(',\n');
            
            return `{\n${items}\n${'  '.repeat(indent)}}`;
        }
        
        return String(ast);
    }

    private escapeHtml(text: string): string {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    private getNonce(): string {
        let text = '';
        const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        for (let i = 0; i < 32; i++) {
            text += possible.charAt(Math.floor(Math.random() * possible.length));
        }
        return text;
    }

    public dispose(): void {
        AstViewerPanel.currentPanel = undefined;
        this.panel.dispose();
        while (this.disposables.length) {
            const x = this.disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
}
