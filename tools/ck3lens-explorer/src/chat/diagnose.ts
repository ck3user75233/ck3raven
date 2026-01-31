/**
 * CK3 Raven Health Diagnostics
 *
 * Provides health checks for the chat participant.
 * V1 Brief: mcp_tools_registered field (not "reachable" - reflects reality).
 */

import * as vscode from 'vscode';

/**
 * Health check result
 */
export interface HealthResult {
    /** Version of the extension */
    extension_version: string;

    /** Whether ck3raven tools are registered (not reachability - just existence) */
    mcp_tools_registered: boolean;

    /** Count of ck3raven tools found */
    mcp_tool_count: number;

    /** List of ck3raven tool names (if any) */
    mcp_tools: string[];

    /** Current workspace folders */
    workspace_folders: string[];

    /** Current playset (if detectable) */
    active_playset?: string;

    /** Timestamp of health check */
    timestamp: string;
}

/**
 * Run health diagnostics
 */
export async function runHealthCheck(
    extensionVersion: string
): Promise<HealthResult> {
    // Get MCP tools
    const allTools = vscode.lm.tools;

    // Filter to ck3raven tools (conservative filter from Q4)
    const ck3Tools = allTools.filter(tool =>
        tool.name.includes('ck3_') || tool.name.includes('ck3lens')
    );

    // Get workspace folders
    const workspaceFolders = vscode.workspace.workspaceFolders?.map(
        f => f.uri.fsPath
    ) || [];

    return {
        extension_version: extensionVersion,
        mcp_tools_registered: ck3Tools.length > 0,
        mcp_tool_count: ck3Tools.length,
        mcp_tools: ck3Tools.map(t => t.name),
        workspace_folders: workspaceFolders,
        active_playset: undefined, // V1: Not detecting from MCP
        timestamp: new Date().toISOString()
    };
}

/**
 * Format health result for display in chat
 */
export function formatHealthForChat(health: HealthResult): string {
    const lines: string[] = [];

    lines.push('## CK3 Raven Health Check\n');

    // Extension
    lines.push(`**Extension Version:** ${health.extension_version}`);

    // MCP Status
    if (health.mcp_tools_registered) {
        lines.push(`**MCP Tools:** ✅ ${health.mcp_tool_count} tools registered`);
    } else {
        lines.push('**MCP Tools:** ⚠️ No tools registered');
        lines.push('');
        lines.push('> Try initializing the MCP server or reloading the window.');
    }

    // Workspace
    if (health.workspace_folders.length > 0) {
        lines.push(`**Workspace:** ${health.workspace_folders[0]}`);
    } else {
        lines.push('**Workspace:** ⚠️ No workspace open');
    }

    // Playset
    if (health.active_playset) {
        lines.push(`**Active Playset:** ${health.active_playset}`);
    }

    lines.push('');
    lines.push(`*Checked at ${health.timestamp}*`);

    return lines.join('\n');
}
