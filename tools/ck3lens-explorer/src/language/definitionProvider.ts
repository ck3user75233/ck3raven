/**
 * Definition Provider - Go to Definition support for Paradox script
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

export class DefinitionProvider implements vscode.DefinitionProvider {
    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    async provideDefinition(
        document: vscode.TextDocument,
        position: vscode.Position,
        token: vscode.CancellationToken
    ): Promise<vscode.Definition | null> {
        const wordRange = document.getWordRangeAtPosition(position, /[a-zA-Z_][a-zA-Z0-9_]*/);
        if (!wordRange) {
            return null;
        }

        const word = document.getText(wordRange);
        if (!word || word.length < 2) {
            return null;
        }

        this.logger.debug(`Looking for definition of: ${word}`);

        try {
            // Search for exact symbol match
            const results = await this.session.searchSymbols(word, undefined, 10);
            
            // Filter to exact matches
            const exactMatches = results.filter(r => r.name === word);
            
            if (exactMatches.length === 0) {
                return null;
            }

            // Return locations for all matches
            return exactMatches.map(match => {
                const uri = vscode.Uri.file(match.relpath);
                const pos = new vscode.Position(match.line - 1, 0);
                return new vscode.Location(uri, pos);
            });

        } catch (error) {
            this.logger.error('Definition lookup failed', error);
            return null;
        }
    }
}
