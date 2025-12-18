/**
 * Hover Provider - Show info on hover for Paradox script
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

export class HoverProvider implements vscode.HoverProvider {
    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    async provideHover(
        document: vscode.TextDocument,
        position: vscode.Position,
        token: vscode.CancellationToken
    ): Promise<vscode.Hover | null> {
        const wordRange = document.getWordRangeAtPosition(position, /[a-zA-Z_][a-zA-Z0-9_]*/);
        if (!wordRange) {
            return null;
        }

        const word = document.getText(wordRange);
        if (!word || word.length < 2) {
            return null;
        }

        try {
            // Search for this symbol
            const results = await this.session.searchSymbols(word, undefined, 5);
            const match = results.find(r => r.name === word);
            
            if (!match) {
                // Check if it's a known keyword/scope
                const builtinInfo = this.getBuiltinInfo(word);
                if (builtinInfo) {
                    return new vscode.Hover(builtinInfo, wordRange);
                }
                return null;
            }

            // Build hover content
            const markdown = new vscode.MarkdownString();
            markdown.isTrusted = true;

            // Symbol name and type
            markdown.appendMarkdown(`### ${match.name}\n\n`);
            markdown.appendMarkdown(`**Type:** \`${match.symbolType}\`\n\n`);
            markdown.appendMarkdown(`**Mod:** ${match.mod}\n\n`);
            markdown.appendMarkdown(`**File:** [${match.relpath}](${vscode.Uri.file(match.relpath).toString()})\n\n`);
            markdown.appendMarkdown(`**Line:** ${match.line}\n`);

            return new vscode.Hover(markdown, wordRange);

        } catch (error) {
            this.logger.debug(`Hover lookup failed for ${word}: ${error}`);
            return null;
        }
    }

    /**
     * Get info for built-in keywords and scopes
     */
    private getBuiltinInfo(word: string): vscode.MarkdownString | null {
        const builtins: { [key: string]: string } = {
            // Control flow
            'if': '**if** block - conditional execution\n\n```\nif = { limit = { ... } ... }\n```',
            'else': '**else** block - alternative branch for if\n\n```\nelse = { ... }\n```',
            'else_if': '**else_if** block - chained conditional\n\n```\nelse_if = { limit = { ... } ... }\n```',
            'limit': '**limit** - conditions that must be met\n\n```\nlimit = { trigger = yes }\n```',
            'trigger': '**trigger** - condition block for validation\n\n```\ntrigger = { is_alive = yes }\n```',
            'effect': '**effect** - actions to perform\n\n```\neffect = { add_gold = 100 }\n```',
            
            // Scopes
            'root': '**root** - the original scope that started the chain',
            'this': '**this** - current scope (implicit)',
            'prev': '**prev** - previous scope in the chain',
            'from': '**from** - scope passed from calling context',
            'scope': '**scope:** - reference to a saved scope\n\n```\nscope:my_target = { ... }\n```',
            
            // Common triggers
            'is_alive': '**is_alive** - check if character is alive\n\n```\nis_alive = yes/no\n```',
            'has_trait': '**has_trait** - check if character has trait\n\n```\nhas_trait = brave\n```',
            'has_culture': '**has_culture** - check character\'s culture\n\n```\nhas_culture = culture:english\n```',
            'has_faith': '**has_faith** - check character\'s faith\n\n```\nhas_faith = faith:catholic\n```',
            
            // Common effects
            'add_gold': '**add_gold** - give gold to character\n\n```\nadd_gold = 100\nadd_gold = { value = 50 }\n```',
            'add_prestige': '**add_prestige** - give prestige\n\n```\nadd_prestige = 100\n```',
            'add_piety': '**add_piety** - give piety\n\n```\nadd_piety = 100\n```',
            'add_trait': '**add_trait** - give trait to character\n\n```\nadd_trait = brave\n```',
            'remove_trait': '**remove_trait** - remove trait from character\n\n```\nremove_trait = craven\n```',
            'trigger_event': '**trigger_event** - fire an event\n\n```\ntrigger_event = my_event.001\ntrigger_event = { id = my_event.001 days = 5 }\n```',
            
            // Boolean
            'yes': '**yes** - boolean true',
            'no': '**no** - boolean false',
            
            // Logic operators
            'AND': '**AND** - all conditions must be true (implicit in most blocks)',
            'OR': '**OR** - at least one condition must be true',
            'NOT': '**NOT** - negate the condition',
            'NOR': '**NOR** - none of the conditions are true',
            'NAND': '**NAND** - not all conditions are true'
        };

        const info = builtins[word];
        if (info) {
            const md = new vscode.MarkdownString(info);
            md.isTrusted = true;
            return md;
        }

        return null;
    }
}
