/**
 * CK3 Studio Panel - File creation and editing with real-time validation
 * 
 * Features:
 * - Create new files in live mod directories
 * - Real-time syntax validation as you type
 * - Symbol recognition and highlighting
 * - Autocomplete for triggers, effects, scopes
 * - File templates for common content types
 * - Copy-from-vanilla for overrides
 */

import * as vscode from 'vscode';
import { CK3LensSession } from '../session';
import { Logger } from '../utils/logger';

/**
 * File template types
 */
export type TemplateType = 
    | 'event' 
    | 'decision' 
    | 'trait' 
    | 'culture' 
    | 'tradition'
    | 'religion'
    | 'on_action'
    | 'scripted_effect'
    | 'scripted_trigger'
    | 'character_interaction'
    | 'empty';

/**
 * Template definitions with scaffolding
 */
export const FILE_TEMPLATES: Record<TemplateType, {
    displayName: string;
    description: string;
    folder: string;
    extension: string;
    content: string;
}> = {
    event: {
        displayName: 'Event',
        description: 'Character or game event',
        folder: 'events',
        extension: '.txt',
        content: `namespace = {{NAMESPACE}}

# {{EVENT_NAME}}
{{NAMESPACE}}.0001 = {
    type = character_event
    title = {{NAMESPACE}}.0001.t
    desc = {{NAMESPACE}}.0001.desc
    theme = default
    
    trigger = {
        is_alive = yes
    }
    
    immediate = {
        # Immediate effects
    }
    
    option = {
        name = {{NAMESPACE}}.0001.a
        # Option effects
    }
}
`
    },
    decision: {
        displayName: 'Decision',
        description: 'Player decision',
        folder: 'common/decisions',
        extension: '.txt',
        content: `{{DECISION_ID}} = {
    picture = "gfx/interface/illustrations/decisions/decision_misc.dds"
    
    desc = {{DECISION_ID}}_desc
    selection_tooltip = {{DECISION_ID}}_tooltip
    
    is_shown = {
        is_ruler = yes
    }
    
    is_valid_showing_failures_only = {
        is_available_adult = yes
    }
    
    cost = {
        gold = 50
    }
    
    effect = {
        # Decision effects
    }
    
    ai_check_interval = 120
    ai_potential = {
        always = yes
    }
    ai_will_do = {
        base = 0
    }
}
`
    },
    trait: {
        displayName: 'Trait',
        description: 'Character trait',
        folder: 'common/traits',
        extension: '.txt',
        content: `{{TRAIT_ID}} = {
    index = 1  # Unique index for save compatibility
    
    # Categories
    personality = yes
    # education = yes
    # lifestyle = yes
    # commander = yes
    
    # Opposites
    # opposites = { trait_opposite }
    
    # Character modifiers
    diplomacy = 1
    martial = 0
    stewardship = 0
    intrigue = 0
    learning = 0
    prowess = 0
    
    # Opinion modifiers
    same_opinion = 10
    opposite_opinion = -10
    
    # AI weights
    ai_rationality = 0
    ai_boldness = 0
    ai_compassion = 0
    ai_greed = 0
    ai_honor = 0
    ai_vengefulness = 0
    ai_zeal = 0
    
    # Visual
    # icon = "gfx/interface/icons/traits/trait_icon.dds"
}
`
    },
    culture: {
        displayName: 'Culture',
        description: 'Culture definition',
        folder: 'common/culture/cultures',
        extension: '.txt',
        content: `{{CULTURE_ID}} = {
    color = { 0.5 0.5 0.5 }
    
    ethos = ethos_courtly
    heritage = heritage_west_germanic
    language = language_german
    martial_custom = martial_custom_male_only
    
    traditions = {
        tradition_example
    }
    
    name_list = name_list_german
    
    coa_gfx = { western_coa_gfx }
    building_gfx = { western_building_gfx }
    clothing_gfx = { western_clothing_gfx }
    unit_gfx = { western_unit_gfx }
}
`
    },
    tradition: {
        displayName: 'Tradition',
        description: 'Culture tradition',
        folder: 'common/culture/traditions',
        extension: '.txt',
        content: `{{TRADITION_ID}} = {
    category = realm
    
    layers = {
        0 = martial
        1 = indian
        4 = leadership.dds
    }
    
    is_shown = {
        # Show conditions
    }
    
    can_pick = {
        # Pick requirements
    }
    
    parameters = {
        # Tradition parameters
    }
    
    character_modifier = {
        # Character modifiers
    }
    
    culture_modifier = {
        # Culture modifiers
    }
    
    cost = {
        prestige = {
            add = {
                value = tradition_base_cost
            }
        }
    }
    
    ai_will_do = {
        value = 100
    }
}
`
    },
    religion: {
        displayName: 'Religion/Faith',
        description: 'Religion or faith definition',
        folder: 'common/religion/religions',
        extension: '.txt',
        content: `{{RELIGION_ID}} = {
    family = rf_pagan
    
    doctrine = doctrine_pluralism_fundamentalist
    doctrine = doctrine_theocracy_temporal
    
    pagan_roots = yes
    
    traits = {
        virtues = { brave just generous }
        sins = { craven arbitrary greedy }
    }
}
`
    },
    on_action: {
        displayName: 'On Action',
        description: 'Event trigger hook',
        folder: 'common/on_action',
        extension: '.txt',
        content: `# {{ON_ACTION_NAME}} - {{DESCRIPTION}}

on_{{ACTION_TYPE}} = {
    on_actions = {
        # Chain to other on_actions
    }
    
    effect = {
        # Immediate effects
    }
    
    events = {
        # Events to fire
    }
    
    random_events = {
        chance_to_happen = 50
        # chance_of_no_event = { ... }
        
        100 = event_namespace.0001
    }
}
`
    },
    scripted_effect: {
        displayName: 'Scripted Effect',
        description: 'Reusable effect script',
        folder: 'common/scripted_effects',
        extension: '.txt',
        content: `# {{EFFECT_NAME}}
# Description: {{DESCRIPTION}}
# Scope: character
# Parameters: 
#   - $PARAM$ = value

{{EFFECT_ID}} = {
    # Effect implementation
    
    if = {
        limit = {
            # Conditions
        }
        # Effects
    }
}
`
    },
    scripted_trigger: {
        displayName: 'Scripted Trigger',
        description: 'Reusable trigger script',
        folder: 'common/scripted_triggers',
        extension: '.txt',
        content: `# {{TRIGGER_NAME}}
# Description: {{DESCRIPTION}}
# Scope: character
# Returns: yes/no

{{TRIGGER_ID}} = {
    # Trigger conditions
    
    OR = {
        # Alternative conditions
    }
    
    # Negated conditions
    NOT = {
        # Must not match
    }
}
`
    },
    character_interaction: {
        displayName: 'Character Interaction',
        description: 'Interaction between characters',
        folder: 'common/character_interactions',
        extension: '.txt',
        content: `{{INTERACTION_ID}} = {
    category = interaction_category_friendly
    
    desc = {{INTERACTION_ID}}_desc
    
    is_shown = {
        NOT = { scope:actor = scope:recipient }
    }
    
    is_valid_showing_failures_only = {
        scope:actor = {
            is_available_adult = yes
        }
    }
    
    on_accept = {
        # Accept effects
    }
    
    on_decline = {
        # Decline effects
    }
    
    ai_accept = {
        base = 0
        
        modifier = {
            add = 20
            opinion = { target = scope:actor value >= 50 }
        }
    }
    
    ai_targets = {
        ai_recipients = family
    }
    
    ai_frequency = 24
    
    ai_potential = {
        is_at_war = no
    }
    
    ai_will_do = {
        base = 0
    }
}
`
    },
    empty: {
        displayName: 'Empty File',
        description: 'Blank file',
        folder: '',
        extension: '.txt',
        content: `# {{FILENAME}}
# Created: {{DATE}}
# Mod: {{MOD_NAME}}

`
    }
};

/**
 * Studio panel for file creation/editing
 */
export class StudioPanel {
    public static currentPanel: StudioPanel | undefined;
    public static readonly viewType = 'ck3lens.studio';

    private readonly panel: vscode.WebviewPanel;
    private readonly extensionUri: vscode.Uri;
    private disposables: vscode.Disposable[] = [];

    private constructor(
        panel: vscode.WebviewPanel,
        extensionUri: vscode.Uri,
        private readonly session: CK3LensSession,
        private readonly logger: Logger
    ) {
        this.panel = panel;
        this.extensionUri = extensionUri;

        this.update();

        this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
        
        this.panel.webview.onDidReceiveMessage(
            (message: { command: string; [key: string]: unknown }) => this.handleMessage(message),
            null,
            this.disposables
        );
    }

    /**
     * Create or show the Studio panel
     */
    public static createOrShow(
        extensionUri: vscode.Uri,
        session: CK3LensSession,
        logger: Logger
    ): StudioPanel {
        const column = vscode.ViewColumn.One;

        if (StudioPanel.currentPanel) {
            StudioPanel.currentPanel.panel.reveal(column);
            return StudioPanel.currentPanel;
        }

        const panel = vscode.window.createWebviewPanel(
            StudioPanel.viewType,
            'CK3 Studio',
            column,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [extensionUri]
            }
        );

        StudioPanel.currentPanel = new StudioPanel(panel, extensionUri, session, logger);
        return StudioPanel.currentPanel;
    }

    /**
     * Handle messages from the webview
     */
    private async handleMessage(message: { command: string; [key: string]: unknown }): Promise<void> {
        switch (message.command) {
            case 'getLiveMods':
                const mods = await this.session.getLiveMods();
                this.panel.webview.postMessage({ command: 'liveMods', mods });
                break;

            case 'getTemplates':
                const templates = Object.entries(FILE_TEMPLATES).map(([id, t]) => ({
                    id,
                    displayName: t.displayName,
                    description: t.description,
                    folder: t.folder
                }));
                this.panel.webview.postMessage({ command: 'templates', templates });
                break;

            case 'createFile':
                await this.createFile(
                    message.modName as string,
                    message.relPath as string,
                    message.content as string,
                    message.template as TemplateType
                );
                break;

            case 'validateContent':
                await this.validateContent(message.content as string, message.filename as string);
                break;

            case 'copyFromVanilla':
                await this.copyFromVanilla(
                    message.vanillaPath as string,
                    message.modName as string,
                    message.newPath as string
                );
                break;

            case 'searchVanillaFiles':
                await this.searchVanillaFiles(message.query as string);
                break;
        }
    }

    /**
     * Create a new file in a live mod
     */
    private async createFile(
        modName: string,
        relPath: string,
        content: string,
        template?: TemplateType
    ): Promise<void> {
        try {
            // Apply template if specified
            let finalContent = content;
            if (template && FILE_TEMPLATES[template]) {
                finalContent = FILE_TEMPLATES[template].content;
                // Replace placeholders
                const filename = relPath.split('/').pop()?.replace('.txt', '') || 'unnamed';
                finalContent = finalContent
                    .replace(/\{\{FILENAME\}\}/g, filename)
                    .replace(/\{\{DATE\}\}/g, new Date().toISOString().split('T')[0])
                    .replace(/\{\{MOD_NAME\}\}/g, modName)
                    .replace(/\{\{NAMESPACE\}\}/g, filename.toLowerCase().replace(/[^a-z0-9_]/g, '_'))
                    .replace(/\{\{EVENT_NAME\}\}/g, filename)
                    .replace(/\{\{DECISION_ID\}\}/g, filename)
                    .replace(/\{\{TRAIT_ID\}\}/g, filename)
                    .replace(/\{\{CULTURE_ID\}\}/g, filename)
                    .replace(/\{\{TRADITION_ID\}\}/g, filename)
                    .replace(/\{\{RELIGION_ID\}\}/g, filename)
                    .replace(/\{\{EFFECT_ID\}\}/g, filename)
                    .replace(/\{\{TRIGGER_ID\}\}/g, filename)
                    .replace(/\{\{INTERACTION_ID\}\}/g, filename);
            }

            // Validate before writing
            const validation = await this.session.parseContent(finalContent, relPath);
            if (!validation.success) {
                this.panel.webview.postMessage({
                    command: 'createResult',
                    success: false,
                    error: 'Syntax errors in content',
                    errors: validation.errors
                });
                return;
            }

            // Write the file
            const success = await this.session.writeLiveFile(modName, relPath, finalContent);
            
            if (success) {
                this.logger.info(`Created file: ${modName}/${relPath}`);
                this.panel.webview.postMessage({
                    command: 'createResult',
                    success: true,
                    modName,
                    relPath
                });

                // Open the file in editor
                const liveMods = await this.session.getLiveMods();
                const mod = liveMods.find(m => m.name === modName);
                if (mod) {
                    const uri = vscode.Uri.file(`${mod.path}/${relPath}`);
                    await vscode.window.showTextDocument(uri);
                }
            } else {
                this.panel.webview.postMessage({
                    command: 'createResult',
                    success: false,
                    error: 'Failed to write file'
                });
            }
        } catch (error) {
            this.logger.error('Create file failed', error);
            this.panel.webview.postMessage({
                command: 'createResult',
                success: false,
                error: String(error)
            });
        }
    }

    /**
     * Validate content and return errors
     */
    private async validateContent(content: string, filename: string): Promise<void> {
        try {
            const result = await this.session.parseContent(content, filename);
            this.panel.webview.postMessage({
                command: 'validationResult',
                success: result.success,
                errors: result.errors,
                ast: result.ast
            });
        } catch (error) {
            this.logger.error('Validation failed', error);
            this.panel.webview.postMessage({
                command: 'validationResult',
                success: false,
                errors: [{ line: 1, message: String(error) }]
            });
        }
    }

    /**
     * Copy a vanilla file to a mod for override
     */
    private async copyFromVanilla(
        vanillaPath: string,
        modName: string,
        newPath?: string
    ): Promise<void> {
        try {
            // Get vanilla file content from database
            const file = await this.session.getFile(vanillaPath, false);
            if (!file || !file.content) {
                this.panel.webview.postMessage({
                    command: 'copyResult',
                    success: false,
                    error: `Vanilla file not found: ${vanillaPath}`
                });
                return;
            }

            // Use same path in mod or custom path
            const targetPath = newPath || vanillaPath;

            // Write to mod
            const success = await this.session.writeLiveFile(modName, targetPath, file.content);

            this.panel.webview.postMessage({
                command: 'copyResult',
                success,
                modName,
                relPath: targetPath,
                error: success ? undefined : 'Failed to write file'
            });

            if (success) {
                this.logger.info(`Copied vanilla file to ${modName}/${targetPath}`);
            }
        } catch (error) {
            this.logger.error('Copy from vanilla failed', error);
            this.panel.webview.postMessage({
                command: 'copyResult',
                success: false,
                error: String(error)
            });
        }
    }

    /**
     * Search vanilla files for copying
     */
    private async searchVanillaFiles(query: string): Promise<void> {
        try {
            const files = await this.session.listFiles(query);
            this.panel.webview.postMessage({
                command: 'vanillaSearchResult',
                files
            });
        } catch (error) {
            this.logger.error('Vanilla search failed', error);
            this.panel.webview.postMessage({
                command: 'vanillaSearchResult',
                files: [],
                error: String(error)
            });
        }
    }

    /**
     * Update the webview content
     */
    private update(): void {
        this.panel.webview.html = this.getHtmlContent();
    }

    /**
     * Get the HTML content for the webview
     */
    private getHtmlContent(): string {
        const nonce = this.getNonce();

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <title>CK3 Studio</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            padding: 20px;
            color: var(--vscode-foreground);
            background: var(--vscode-editor-background);
            max-width: 800px;
            margin: 0 auto;
        }
        h1 {
            color: var(--vscode-textLink-foreground);
            border-bottom: 1px solid var(--vscode-panel-border);
            padding-bottom: 10px;
        }
        .section {
            margin: 20px 0;
            padding: 16px;
            background: var(--vscode-sideBar-background);
            border-radius: 6px;
            border: 1px solid var(--vscode-panel-border);
        }
        .section-title {
            font-weight: bold;
            font-size: 14px;
            margin-bottom: 12px;
            color: var(--vscode-sideBarSectionHeader-foreground);
        }
        .form-group {
            margin: 12px 0;
        }
        label {
            display: block;
            margin-bottom: 4px;
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
        }
        input, select, textarea {
            width: 100%;
            padding: 8px;
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 4px;
            font-family: inherit;
            box-sizing: border-box;
        }
        textarea {
            min-height: 200px;
            font-family: var(--vscode-editor-font-family);
            font-size: var(--vscode-editor-font-size);
        }
        button {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 10px 20px;
            cursor: pointer;
            border-radius: 4px;
            font-size: 13px;
            margin-right: 8px;
        }
        button:hover {
            background: var(--vscode-button-hoverBackground);
        }
        button.secondary {
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        .template-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 8px;
        }
        .template-card {
            padding: 12px;
            background: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
            cursor: pointer;
            transition: border-color 0.2s;
        }
        .template-card:hover {
            border-color: var(--vscode-focusBorder);
        }
        .template-card.selected {
            border-color: var(--vscode-textLink-foreground);
            background: var(--vscode-list-activeSelectionBackground);
        }
        .template-name {
            font-weight: bold;
            margin-bottom: 4px;
        }
        .template-desc {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
        }
        .error {
            color: var(--vscode-errorForeground);
            background: var(--vscode-inputValidation-errorBackground);
            border: 1px solid var(--vscode-inputValidation-errorBorder);
            padding: 8px;
            border-radius: 4px;
            margin: 8px 0;
        }
        .success {
            color: var(--vscode-testing-iconPassed);
            background: var(--vscode-testing-message-info-decorationBackground);
            padding: 8px;
            border-radius: 4px;
            margin: 8px 0;
        }
        .validation-status {
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 8px 0;
            font-size: 12px;
        }
        .validation-status.valid {
            color: var(--vscode-testing-iconPassed);
        }
        .validation-status.invalid {
            color: var(--vscode-errorForeground);
        }
        .error-list {
            margin: 8px 0;
            padding: 0;
            list-style: none;
        }
        .error-list li {
            padding: 4px 8px;
            font-size: 12px;
            font-family: var(--vscode-editor-font-family);
        }
        .tabs {
            display: flex;
            border-bottom: 1px solid var(--vscode-panel-border);
            margin-bottom: 16px;
        }
        .tab {
            padding: 8px 16px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            color: var(--vscode-foreground);
        }
        .tab.active {
            border-bottom-color: var(--vscode-textLink-foreground);
            color: var(--vscode-textLink-foreground);
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
    <h1>🎨 CK3 Studio</h1>
    
    <div class="tabs">
        <div class="tab active" data-tab="create">Create New</div>
        <div class="tab" data-tab="copy">Copy from Vanilla</div>
    </div>

    <!-- Create New Tab -->
    <div id="create-tab" class="tab-content active">
        <div class="section">
            <div class="section-title">1. Select Mod</div>
            <div class="form-group">
                <label>Target Mod (must be in live mods list)</label>
                <select id="modSelect">
                    <option value="">Loading...</option>
                </select>
            </div>
        </div>

        <div class="section">
            <div class="section-title">2. Choose Template</div>
            <div id="templateGrid" class="template-grid">
                <!-- Templates loaded dynamically -->
            </div>
        </div>

        <div class="section">
            <div class="section-title">3. File Details</div>
            <div class="form-group">
                <label>File Path (relative to mod root, e.g., common/traits/my_trait.txt)</label>
                <input type="text" id="filePath" placeholder="common/traits/my_trait.txt">
            </div>
            <div class="form-group">
                <label>Content (edit template as needed)</label>
                <textarea id="fileContent" placeholder="File content will appear here..."></textarea>
            </div>
            <div id="validationStatus" class="validation-status"></div>
            <div id="errorList"></div>
        </div>

        <div class="section">
            <button id="createBtn">Create File</button>
            <button id="validateBtn" class="secondary">Validate</button>
        </div>

        <div id="createResult"></div>
    </div>

    <!-- Copy from Vanilla Tab -->
    <div id="copy-tab" class="tab-content">
        <div class="section">
            <div class="section-title">Search Vanilla Files</div>
            <div class="form-group">
                <label>Folder path or pattern</label>
                <input type="text" id="vanillaSearch" placeholder="common/traits">
            </div>
            <button id="searchBtn">Search</button>
            <div id="vanillaResults" style="margin-top: 12px; max-height: 300px; overflow-y: auto;"></div>
        </div>

        <div class="section">
            <div class="section-title">Copy To Mod</div>
            <div class="form-group">
                <label>Selected File</label>
                <input type="text" id="selectedVanilla" readonly>
            </div>
            <div class="form-group">
                <label>Target Mod</label>
                <select id="copyModSelect">
                    <option value="">Loading...</option>
                </select>
            </div>
            <div class="form-group">
                <label>Custom Path (leave empty to use same path)</label>
                <input type="text" id="customPath" placeholder="Leave empty for same path">
            </div>
            <button id="copyBtn">Copy to Mod</button>
        </div>

        <div id="copyResult"></div>
    </div>

    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        
        let selectedTemplate = 'empty';
        let liveMods = [];
        let templates = [];

        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab + '-tab').classList.add('active');
            });
        });

        // Request initial data
        vscode.postMessage({ command: 'getLiveMods' });
        vscode.postMessage({ command: 'getTemplates' });

        // Handle messages from extension
        window.addEventListener('message', event => {
            const message = event.data;
            
            switch (message.command) {
                case 'liveMods':
                    liveMods = message.mods || [];
                    updateModSelects();
                    break;

                case 'templates':
                    templates = message.templates || [];
                    renderTemplates();
                    break;

                case 'validationResult':
                    showValidation(message);
                    break;

                case 'createResult':
                    showCreateResult(message);
                    break;

                case 'vanillaSearchResult':
                    showVanillaResults(message.files || []);
                    break;

                case 'copyResult':
                    showCopyResult(message);
                    break;
            }
        });

        function updateModSelects() {
            const html = liveMods.length === 0 
                ? '<option value="">No live mods configured</option>'
                : liveMods.map(m => 
                    '<option value="' + m.name + '">' + m.name + (m.exists ? '' : ' (not found)') + '</option>'
                ).join('');
            
            document.getElementById('modSelect').innerHTML = html;
            document.getElementById('copyModSelect').innerHTML = html;
        }

        function renderTemplates() {
            const grid = document.getElementById('templateGrid');
            grid.innerHTML = templates.map(t => 
                '<div class="template-card' + (t.id === selectedTemplate ? ' selected' : '') + '" data-template="' + t.id + '">' +
                    '<div class="template-name">' + t.displayName + '</div>' +
                    '<div class="template-desc">' + t.description + '</div>' +
                '</div>'
            ).join('');

            grid.querySelectorAll('.template-card').forEach(card => {
                card.addEventListener('click', () => {
                    selectedTemplate = card.dataset.template;
                    grid.querySelectorAll('.template-card').forEach(c => c.classList.remove('selected'));
                    card.classList.add('selected');
                    
                    // Update default path based on template
                    const template = templates.find(t => t.id === selectedTemplate);
                    if (template && template.folder) {
                        const pathInput = document.getElementById('filePath');
                        if (!pathInput.value || pathInput.value.startsWith('common/') || pathInput.value.startsWith('events/')) {
                            pathInput.value = template.folder + '/new_file.txt';
                        }
                    }
                });
            });
        }

        function showValidation(result) {
            const status = document.getElementById('validationStatus');
            const errorList = document.getElementById('errorList');

            if (result.success) {
                status.className = 'validation-status valid';
                status.innerHTML = '✓ Syntax valid';
                errorList.innerHTML = '';
            } else {
                status.className = 'validation-status invalid';
                status.innerHTML = '✗ Syntax errors found';
                errorList.innerHTML = '<ul class="error-list">' +
                    (result.errors || []).map(e => 
                        '<li>Line ' + e.line + ': ' + e.message + '</li>'
                    ).join('') +
                '</ul>';
            }
        }

        function showCreateResult(result) {
            const div = document.getElementById('createResult');
            if (result.success) {
                div.innerHTML = '<div class="success">✓ Created ' + result.modName + '/' + result.relPath + '</div>';
            } else {
                div.innerHTML = '<div class="error">✗ ' + result.error + '</div>';
                if (result.errors) {
                    div.innerHTML += '<ul class="error-list">' +
                        result.errors.map(e => '<li>Line ' + e.line + ': ' + e.message + '</li>').join('') +
                    '</ul>';
                }
            }
        }

        function showVanillaResults(files) {
            const div = document.getElementById('vanillaResults');
            if (files.length === 0) {
                div.innerHTML = '<div style="color: var(--vscode-descriptionForeground)">No files found</div>';
                return;
            }
            div.innerHTML = files.slice(0, 50).map(f => 
                '<div class="template-card" data-path="' + f.relpath + '">' +
                    '<div style="font-size: 12px; word-break: break-all;">' + f.relpath + '</div>' +
                    '<div class="template-desc">' + (f.mod || 'vanilla') + '</div>' +
                '</div>'
            ).join('');

            div.querySelectorAll('.template-card').forEach(card => {
                card.addEventListener('click', () => {
                    document.getElementById('selectedVanilla').value = card.dataset.path;
                    div.querySelectorAll('.template-card').forEach(c => c.classList.remove('selected'));
                    card.classList.add('selected');
                });
            });
        }

        function showCopyResult(result) {
            const div = document.getElementById('copyResult');
            if (result.success) {
                div.innerHTML = '<div class="success">✓ Copied to ' + result.modName + '/' + result.relPath + '</div>';
            } else {
                div.innerHTML = '<div class="error">✗ ' + result.error + '</div>';
            }
        }

        // Button handlers
        document.getElementById('validateBtn').addEventListener('click', () => {
            const content = document.getElementById('fileContent').value;
            const path = document.getElementById('filePath').value;
            vscode.postMessage({ command: 'validateContent', content, filename: path });
        });

        document.getElementById('createBtn').addEventListener('click', () => {
            const modName = document.getElementById('modSelect').value;
            const relPath = document.getElementById('filePath').value;
            const content = document.getElementById('fileContent').value;
            
            if (!modName) {
                alert('Please select a mod');
                return;
            }
            if (!relPath) {
                alert('Please enter a file path');
                return;
            }
            
            vscode.postMessage({ 
                command: 'createFile', 
                modName, 
                relPath, 
                content,
                template: selectedTemplate
            });
        });

        document.getElementById('searchBtn').addEventListener('click', () => {
            const query = document.getElementById('vanillaSearch').value;
            vscode.postMessage({ command: 'searchVanillaFiles', query });
        });

        document.getElementById('copyBtn').addEventListener('click', () => {
            const vanillaPath = document.getElementById('selectedVanilla').value;
            const modName = document.getElementById('copyModSelect').value;
            const customPath = document.getElementById('customPath').value;
            
            if (!vanillaPath) {
                alert('Please select a vanilla file');
                return;
            }
            if (!modName) {
                alert('Please select a mod');
                return;
            }
            
            vscode.postMessage({ 
                command: 'copyFromVanilla', 
                vanillaPath, 
                modName,
                newPath: customPath || undefined
            });
        });

        // Real-time validation on content change (debounced)
        let validateTimeout;
        document.getElementById('fileContent').addEventListener('input', () => {
            clearTimeout(validateTimeout);
            validateTimeout = setTimeout(() => {
                const content = document.getElementById('fileContent').value;
                const path = document.getElementById('filePath').value;
                if (content.trim()) {
                    vscode.postMessage({ command: 'validateContent', content, filename: path });
                }
            }, 500);
        });
    </script>
</body>
</html>`;
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
        StudioPanel.currentPanel = undefined;
        this.panel.dispose();
        while (this.disposables.length) {
            const d = this.disposables.pop();
            if (d) { d.dispose(); }
        }
    }
}
