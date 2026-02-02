/**
 * CK3 Raven Chat Participant
 *
 * Implements @ck3raven chat participant with tool orchestration loop.
 * V1 Brief compliance: tool result feedback loop (Q1), minimal system prompt (Q5).
 */

import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

// Type for tool results (success or error)
interface ToolResultEntry {
    callId: string;
    content: Array<vscode.LanguageModelTextPart | unknown>;
}

export class Ck3RavenParticipant implements vscode.Disposable {
    private participant: vscode.ChatParticipant;
    private disposables: vscode.Disposable[] = [];

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly logger: Logger
    ) {
        // Register the chat participant
        this.participant = vscode.chat.createChatParticipant(
            'ck3raven',
            this.handleRequest.bind(this)
        );

        // Set participant icon - uses existing sidebar icon
        this.participant.iconPath = vscode.Uri.joinPath(
            context.extensionUri,
            'media',
            'ck3lens-sidebar.svg'
        );

        // Set up followup provider
        this.participant.followupProvider = {
            provideFollowups: this.provideFollowups.bind(this)
        };

        // Subscribe to feedback events
        this.disposables.push(
            this.participant.onDidReceiveFeedback(this.handleFeedback.bind(this))
        );
    }

    /**
     * Main request handler - implements tool result feedback loop (Q1)
     */
    private async handleRequest(
        request: vscode.ChatRequest,
        context: vscode.ChatContext,
        stream: vscode.ChatResponseStream,
        token: vscode.CancellationToken
    ): Promise<vscode.ChatResult> {
        // Create turn ID
        const turnId = `turn-${Date.now()}`;

        // Count tool calls for this turn
        let toolCallCount = 0;

        try {
            // Build initial messages
            const messages = this.buildMessages(request, context);

            // Get available MCP tools (Q4 - conservative filter)
            const tools = this.getMcpTools();

            // Full response text accumulator
            let fullResponseText = '';

            // Tool orchestration loop - continues until no more tool calls (Q1)
            let continueLoop = true;
            while (continueLoop && !token.isCancellationRequested) {
                continueLoop = false;

                // Send request to LLM
                const response = await request.model.sendRequest(
                    messages,
                    { tools },
                    token
                );

                // Collect tool calls from this iteration
                const iterationToolCalls: vscode.LanguageModelToolCallPart[] = [];
                const iterationToolResults: ToolResultEntry[] = [];

                // Process response stream
                for await (const part of response.stream) {
                    if (token.isCancellationRequested) break;

                    if (part instanceof vscode.LanguageModelTextPart) {
                        // Stream text to user
                        stream.markdown(part.value);
                        fullResponseText += part.value;

                    } else if (part instanceof vscode.LanguageModelToolCallPart) {
                        // Collect tool call for batch processing
                        iterationToolCalls.push(part);
                    }
                }

                // Execute all tool calls from this iteration
                if (iterationToolCalls.length > 0) {
                    continueLoop = true; // Need another LLM round after tools

                    for (const toolCall of iterationToolCalls) {
                        toolCallCount++;
                        const startTime = Date.now();

                        try {
                            // Show progress
                            stream.progress(`Calling ${this.cleanToolName(toolCall.name)}...`);

                            // Execute the tool via vscode.lm.invokeTool (Q1)
                            const result = await vscode.lm.invokeTool(
                                toolCall.name,
                                {
                                    input: toolCall.input,
                                    toolInvocationToken: request.toolInvocationToken
                                },
                                token
                            );

                            const timing = Date.now() - startTime;
                            this.logger.debug(`Tool ${toolCall.name} completed in ${timing}ms`);

                            // Collect result for feedback to LLM
                            iterationToolResults.push({
                                callId: toolCall.callId,
                                content: result.content
                            });

                        } catch (error) {
                            const timing = Date.now() - startTime;
                            this.logger.error(`Tool ${toolCall.name} failed in ${timing}ms`, error);

                            // Provide error as text content to LLM
                            iterationToolResults.push({
                                callId: toolCall.callId,
                                content: [new vscode.LanguageModelTextPart(`Error: ${String(error)}`)]
                            });
                        }
                    }

                    // CRITICAL: Feed tool results back to LLM (Q1 requirement)
                    // Append assistant message with tool calls
                    messages.push(
                        vscode.LanguageModelChatMessage.Assistant(
                            iterationToolCalls.map(tc =>
                                new vscode.LanguageModelToolCallPart(tc.callId, tc.name, tc.input)
                            )
                        )
                    );

                    // Append user message with tool results
                    messages.push(
                        vscode.LanguageModelChatMessage.User(
                            iterationToolResults.map(tr =>
                                new vscode.LanguageModelToolResultPart(tr.callId, tr.content)
                            )
                        )
                    );
                }
            }

            return {
                metadata: {
                    turnId,
                    toolCallCount
                }
            };

        } catch (error) {
            this.logger.error('Chat request failed', error);
            stream.markdown(`\n\n⚠️ Error: ${error}`);

            return {
                errorDetails: {
                    message: String(error)
                }
            };
        }
    }

    /**
     * Build messages array for LLM request
     */
    private buildMessages(
        request: vscode.ChatRequest,
        context: vscode.ChatContext
    ): vscode.LanguageModelChatMessage[] {
        const messages: vscode.LanguageModelChatMessage[] = [];

        // System prompt as first user message (prefixed for clarity)
        messages.push(
            vscode.LanguageModelChatMessage.User(`SYSTEM: ${this.getSystemPrompt()}`)
        );

        // Add conversation history
        for (const turn of context.history) {
            if (turn instanceof vscode.ChatRequestTurn) {
                messages.push(
                    vscode.LanguageModelChatMessage.User(turn.prompt)
                );
            } else if (turn instanceof vscode.ChatResponseTurn) {
                const text = this.extractResponseText(turn);
                messages.push(
                    vscode.LanguageModelChatMessage.Assistant(text)
                );
            }
        }

        // Add current prompt
        messages.push(
            vscode.LanguageModelChatMessage.User(request.prompt)
        );

        return messages;
    }

    /**
     * Minimal system prompt (Q5 - FINAL)
     */
    private getSystemPrompt(): string {
        return `You are ck3raven.
Use the provided tools when needed.
Tool names are dynamic; use EXACT tool name strings provided in tool list for this request.`;
    }

    /**
     * Get MCP tools available for this request (Q4 - conservative filter)
     */
    private getMcpTools(): vscode.LanguageModelChatTool[] {
        const allTools = vscode.lm.tools;

        // Conservative filter: only ck3_* tools from our MCP server
        return allTools.filter(tool =>
            tool.name.includes('ck3_') || tool.name.includes('ck3lens')
        );
    }

    /**
     * Clean tool name for display (strip instance prefix)
     */
    private cleanToolName(toolName: string): string {
        return toolName.replace(/^mcp_ck3_lens_[^_]+_/, '');
    }

    /**
     * Extract text from a response turn
     */
    private extractResponseText(turn: vscode.ChatResponseTurn): string {
        let text = '';
        for (const part of turn.response) {
            if (part instanceof vscode.ChatResponseMarkdownPart) {
                text += part.value.value;
            }
        }
        return text;
    }

    /**
     * Provide followup suggestions
     */
    private provideFollowups(
        _result: vscode.ChatResult,
        _context: vscode.ChatContext,
        _token: vscode.CancellationToken
    ): vscode.ProviderResult<vscode.ChatFollowup[]> {
        return [
            {
                prompt: 'Show me more details',
                label: 'More details'
            },
            {
                prompt: 'Search for related symbols',
                label: 'Find related'
            }
        ];
    }

    /**
     * Handle user feedback on responses
     */
    private handleFeedback(feedback: vscode.ChatResultFeedback): void {
        this.logger.info(`Received feedback: ${feedback.kind}`);
    }

    dispose(): void {
        this.participant.dispose();
        this.disposables.forEach(d => d.dispose());
    }
}
