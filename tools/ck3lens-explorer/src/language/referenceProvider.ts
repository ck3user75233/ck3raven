/**
 * Reference Provider - Find All References support for Paradox script
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

export class ReferenceProvider implements vscode.ReferenceProvider {
    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    async provideReferences(
        document: vscode.TextDocument,
        position: vscode.Position,
        context: vscode.ReferenceContext,
        token: vscode.CancellationToken
    ): Promise<vscode.Location[] | null> {
        const wordRange = document.getWordRangeAtPosition(position, /[a-zA-Z_][a-zA-Z0-9_]*/);
        if (!wordRange) {
            return null;
        }

        const word = document.getText(wordRange);
        if (!word || word.length < 2) {
            return null;
        }

        this.logger.debug(`Finding references for: ${word}`);

        try {
            // Search for all occurrences of this symbol
            const results = await this.session.searchSymbols(word, undefined, 100);
            
            if (results.length === 0) {
                return null;
            }

            // Convert to locations
            const locations = results
                .filter(r => r.name === word)
                .map(match => {
                    const uri = vscode.Uri.file(match.relpath);
                    const pos = new vscode.Position(match.line - 1, 0);
                    return new vscode.Location(uri, pos);
                });

            // If includeDeclaration is false, filter out the current position
            if (!context.includeDeclaration) {
                return locations.filter(loc => 
                    !(loc.uri.fsPath === document.uri.fsPath && 
                      loc.range.start.line === position.line)
                );
            }

            return locations;

        } catch (error) {
            this.logger.error('Reference lookup failed', error);
            return null;
        }
    }
}
