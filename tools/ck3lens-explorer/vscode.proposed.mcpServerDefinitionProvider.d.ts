/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

// https://github.com/microsoft/vscode/issues/235850

declare module 'vscode' {

	export interface McpServerDefinition {
		/**
		 * The label of the MCP server.
		 */
		readonly label: string;
	}

	export class McpStdioServerDefinition implements McpServerDefinition {
		/**
		 * The label of the MCP server.
		 */
		readonly label: string;

		/**
		 * The command to run to start the MCP server.
		 */
		readonly command: string;

		/**
		 * The arguments to pass to the command.
		 */
		readonly args: readonly string[];

		/**
		 * The environment variables to set when running the command.
		 */
		readonly env: Readonly<Record<string, string | number | null>>;

		/**
		 * The version of the MCP server.
		 */
		readonly version: string;

		/**
		 * Creates a new MCP stdio server definition.
		 * @param label The label of the MCP server.
		 * @param command The command to run to start the MCP server.
		 * @param args The arguments to pass to the command.
		 * @param env The environment variables to set when running the command.
		 * @param version The version of the MCP server.
		 */
		constructor(
			label: string,
			command: string,
			args?: readonly string[],
			env?: Record<string, string | number | null>,
			version?: string
		);
	}

	export interface McpServerDefinitionProvider {
		/**
		 * Provides MCP server definitions.
		 * @param token A cancellation token.
		 * @returns A list of MCP server definitions.
		 */
		provideMcpServerDefinitions(token: CancellationToken): ProviderResult<McpServerDefinition[]>;

		/**
		 * An event that signals that the MCP server definitions have changed.
		 */
		onDidChangeMcpServerDefinitions?: Event<void>;
	}

	export namespace lm {
		/**
		 * Registers an MCP server definition provider.
		 * @param id The ID of the provider. Must match an entry in the extension's package.json contributes.mcpServerDefinitionProviders.
		 * @param provider The provider to register.
		 * @returns A disposable that unregisters the provider.
		 */
		export function registerMcpServerDefinitionProvider(
			id: string,
			provider: McpServerDefinitionProvider
		): Disposable;
	}
}
