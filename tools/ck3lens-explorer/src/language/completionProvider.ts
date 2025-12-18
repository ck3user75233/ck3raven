/**
 * Completion Provider - IntelliSense for Paradox script
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

export class CompletionProvider implements vscode.CompletionItemProvider {
    constructor(
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {}

    async provideCompletionItems(
        document: vscode.TextDocument,
        position: vscode.Position,
        token: vscode.CancellationToken,
        context: vscode.CompletionContext
    ): Promise<vscode.CompletionItem[] | null> {
        const linePrefix = document.lineAt(position).text.slice(0, position.character);
        
        // Get the word being typed
        const wordMatch = linePrefix.match(/[a-zA-Z_][a-zA-Z0-9_]*$/);
        const prefix = wordMatch ? wordMatch[0] : '';

        if (prefix.length < 2) {
            // Only provide completions for 2+ character prefixes
            return this.getKeywordCompletions();
        }

        try {
            const items: vscode.CompletionItem[] = [];

            // Search for matching symbols
            const results = await this.session.searchSymbols(prefix, undefined, 20);
            
            for (const result of results) {
                const item = new vscode.CompletionItem(
                    result.name,
                    this.getCompletionKind(result.symbolType)
                );
                item.detail = `${result.symbolType} (${result.mod})`;
                item.documentation = new vscode.MarkdownString(
                    `**${result.name}**\n\n` +
                    `Type: \`${result.symbolType}\`\n\n` +
                    `Mod: ${result.mod}\n\n` +
                    `File: ${result.relpath}`
                );
                item.sortText = `1_${result.name}`; // Prioritize over keywords
                items.push(item);
            }

            // Add keyword completions
            items.push(...this.getKeywordCompletions(prefix));

            return items;

        } catch (error) {
            this.logger.debug(`Completion failed: ${error}`);
            return this.getKeywordCompletions(prefix);
        }
    }

    private getCompletionKind(symbolType: string): vscode.CompletionItemKind {
        const kindMap: { [key: string]: vscode.CompletionItemKind } = {
            'trait': vscode.CompletionItemKind.Property,
            'event': vscode.CompletionItemKind.Event,
            'decision': vscode.CompletionItemKind.Method,
            'on_action': vscode.CompletionItemKind.Event,
            'scripted_effect': vscode.CompletionItemKind.Function,
            'scripted_trigger': vscode.CompletionItemKind.Function,
            'culture': vscode.CompletionItemKind.Class,
            'religion': vscode.CompletionItemKind.Module,
            'faith': vscode.CompletionItemKind.Module,
            'building': vscode.CompletionItemKind.Constructor,
            'government': vscode.CompletionItemKind.Struct,
            'law': vscode.CompletionItemKind.EnumMember,
            'tradition': vscode.CompletionItemKind.Interface
        };

        return kindMap[symbolType] || vscode.CompletionItemKind.Reference;
    }

    private getKeywordCompletions(prefix?: string): vscode.CompletionItem[] {
        const keywords = [
            // Control flow
            { name: 'if', snippet: 'if = {\n\tlimit = { $1 }\n\t$2\n}', detail: 'Conditional block' },
            { name: 'else', snippet: 'else = {\n\t$1\n}', detail: 'Else branch' },
            { name: 'else_if', snippet: 'else_if = {\n\tlimit = { $1 }\n\t$2\n}', detail: 'Else-if branch' },
            { name: 'limit', snippet: 'limit = {\n\t$1\n}', detail: 'Condition block' },
            { name: 'trigger', snippet: 'trigger = {\n\t$1\n}', detail: 'Trigger block' },
            { name: 'effect', snippet: 'effect = {\n\t$1\n}', detail: 'Effect block' },
            
            // Common effects
            { name: 'add_gold', snippet: 'add_gold = $1', detail: 'Add gold' },
            { name: 'add_prestige', snippet: 'add_prestige = $1', detail: 'Add prestige' },
            { name: 'add_piety', snippet: 'add_piety = $1', detail: 'Add piety' },
            { name: 'add_trait', snippet: 'add_trait = $1', detail: 'Add trait' },
            { name: 'remove_trait', snippet: 'remove_trait = $1', detail: 'Remove trait' },
            { name: 'trigger_event', snippet: 'trigger_event = { id = $1 }', detail: 'Trigger event' },
            { name: 'hidden_effect', snippet: 'hidden_effect = {\n\t$1\n}', detail: 'Hidden effect block' },
            { name: 'show_as_tooltip', snippet: 'show_as_tooltip = {\n\t$1\n}', detail: 'Show as tooltip' },
            
            // Common triggers
            { name: 'is_alive', snippet: 'is_alive = ${1|yes,no|}', detail: 'Check if alive' },
            { name: 'has_trait', snippet: 'has_trait = $1', detail: 'Check trait' },
            { name: 'has_culture', snippet: 'has_culture = culture:$1', detail: 'Check culture' },
            { name: 'has_faith', snippet: 'has_faith = faith:$1', detail: 'Check faith' },
            { name: 'has_government', snippet: 'has_government = $1', detail: 'Check government' },
            { name: 'is_ruler', snippet: 'is_ruler = ${1|yes,no|}', detail: 'Check if ruler' },
            { name: 'is_landed', snippet: 'is_landed = ${1|yes,no|}', detail: 'Check if landed' },
            
            // Scopes
            { name: 'every_vassal', snippet: 'every_vassal = {\n\t$1\n}', detail: 'Iterate vassals' },
            { name: 'every_child', snippet: 'every_child = {\n\t$1\n}', detail: 'Iterate children' },
            { name: 'random_vassal', snippet: 'random_vassal = {\n\tlimit = { $1 }\n\t$2\n}', detail: 'Random vassal' },
            { name: 'any_vassal', snippet: 'any_vassal = {\n\t$1\n}', detail: 'Any vassal matches' },
            
            // Logic
            { name: 'AND', snippet: 'AND = {\n\t$1\n}', detail: 'All conditions true' },
            { name: 'OR', snippet: 'OR = {\n\t$1\n}', detail: 'Any condition true' },
            { name: 'NOT', snippet: 'NOT = { $1 }', detail: 'Negate condition' },
            { name: 'NOR', snippet: 'NOR = {\n\t$1\n}', detail: 'No conditions true' },
            
            // Random
            { name: 'random', snippet: 'random = {\n\tchance = $1\n\t$2\n}', detail: 'Random chance' },
            { name: 'random_list', snippet: 'random_list = {\n\t$1 = {\n\t\t$2\n\t}\n}', detail: 'Weighted random list' },
            
            // Variables
            { name: 'save_scope_as', snippet: 'save_scope_as = $1', detail: 'Save current scope' },
            { name: 'save_scope_value_as', snippet: 'save_scope_value_as = {\n\tname = $1\n\tvalue = $2\n}', detail: 'Save value' },
            { name: 'set_variable', snippet: 'set_variable = {\n\tname = $1\n\tvalue = $2\n}', detail: 'Set variable' }
        ];

        const items: vscode.CompletionItem[] = [];

        for (const kw of keywords) {
            if (!prefix || kw.name.startsWith(prefix)) {
                const item = new vscode.CompletionItem(kw.name, vscode.CompletionItemKind.Keyword);
                item.insertText = new vscode.SnippetString(kw.snippet);
                item.detail = kw.detail;
                item.sortText = `2_${kw.name}`; // After symbol matches
                items.push(item);
            }
        }

        return items;
    }
}
