/**
 * CK3 Lens Setup Wizard
 * 
 * Guides users through installation and configuration of CK3 Lens.
 * - Checks all dependencies (Python, packages)
 * - Auto-detects paths where possible
 * - Prompts for user-provided paths (Steam workshop, local mods)
 * - Validates everything works before completing
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn, execSync } from 'child_process';
import { Logger } from '../utils/logger';

export interface SetupResult {
    success: boolean;
    errors: string[];
    warnings: string[];
    config: SetupConfig;
}

export interface SetupConfig {
    pythonPath: string;
    ck3ravenPath: string;
    databasePath: string;
    vanillaPath: string;
    workshopPath: string;
    localModsPath: string;
}

export interface DependencyCheck {
    name: string;
    status: 'ok' | 'missing' | 'error';
    version?: string;
    message?: string;
    canAutoInstall: boolean;
}

export interface PathCheck {
    name: string;
    path: string;
    status: 'ok' | 'missing' | 'invalid';
    message?: string;
    isRequired: boolean;
    isUserProvided: boolean;
}

/**
 * Main Setup Wizard class
 */
export class SetupWizard {
    private readonly context: vscode.ExtensionContext;
    private readonly logger: Logger;
    private config: Partial<SetupConfig> = {};
    private pythonPath: string = '';

    constructor(context: vscode.ExtensionContext, logger: Logger) {
        this.context = context;
        this.logger = logger;
    }

    /**
     * Run the complete setup wizard
     */
    async run(): Promise<SetupResult> {
        const errors: string[] = [];
        const warnings: string[] = [];

        try {
            // Show welcome message
            const startSetup = await vscode.window.showInformationMessage(
                'Welcome to CK3 Lens Setup! This wizard will configure your environment.',
                'Start Setup',
                'Cancel'
            );

            if (startSetup !== 'Start Setup') {
                return { success: false, errors: ['Setup cancelled by user'], warnings: [], config: {} as SetupConfig };
            }

            // Step 1: Check and setup Python
            await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: 'CK3 Lens Setup',
                cancellable: true
            }, async (progress, token) => {
                
                // Step 1: Python Check
                progress.report({ message: 'Checking Python installation...', increment: 0 });
                const pythonResult = await this.checkAndSetupPython();
                if (!pythonResult.success) {
                    errors.push(...pythonResult.errors);
                    throw new Error('Python setup failed');
                }
                this.pythonPath = pythonResult.pythonPath!;
                this.config.pythonPath = this.pythonPath;

                if (token.isCancellationRequested) throw new Error('Cancelled');

                // Step 2: Detect ck3raven path
                progress.report({ message: 'Locating ck3raven...', increment: 15 });
                const ck3ravenResult = await this.detectCk3ravenPath();
                if (!ck3ravenResult.success) {
                    errors.push(...ck3ravenResult.errors);
                    throw new Error('Could not locate ck3raven');
                }
                this.config.ck3ravenPath = ck3ravenResult.path!;

                if (token.isCancellationRequested) throw new Error('Cancelled');

                // Step 3: Check Python packages
                progress.report({ message: 'Checking Python packages...', increment: 15 });
                const packagesResult = await this.checkAndInstallPackages();
                if (packagesResult.errors.length > 0) {
                    errors.push(...packagesResult.errors);
                }
                warnings.push(...packagesResult.warnings);

                if (token.isCancellationRequested) throw new Error('Cancelled');

                // Step 4: Detect/prompt for game paths
                progress.report({ message: 'Configuring game paths...', increment: 20 });
                const pathsResult = await this.setupGamePaths();
                if (!pathsResult.success) {
                    errors.push(...pathsResult.errors);
                }
                warnings.push(...pathsResult.warnings);

                if (token.isCancellationRequested) throw new Error('Cancelled');

                // Step 5: Database path
                progress.report({ message: 'Configuring database path...', increment: 15 });
                await this.setupDatabasePath();

                if (token.isCancellationRequested) throw new Error('Cancelled');

                // Step 6: Verify everything works
                progress.report({ message: 'Verifying configuration...', increment: 20 });
                const verifyResult = await this.verifySetup();
                if (!verifyResult.success) {
                    errors.push(...verifyResult.errors);
                }
                warnings.push(...verifyResult.warnings);

                // Step 7: Save configuration
                progress.report({ message: 'Saving configuration...', increment: 15 });
                await this.saveConfiguration();
            });

            const success = errors.length === 0;
            
            if (success) {
                vscode.window.showInformationMessage(
                    '✅ CK3 Lens setup completed successfully! Please reload the window.',
                    'Reload Window'
                ).then(selection => {
                    if (selection === 'Reload Window') {
                        vscode.commands.executeCommand('workbench.action.reloadWindow');
                    }
                });
            } else {
                vscode.window.showErrorMessage(
                    `CK3 Lens setup completed with errors:\n${errors.join('\n')}`,
                    'View Errors'
                );
            }

            return {
                success,
                errors,
                warnings,
                config: this.config as SetupConfig
            };

        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            if (message !== 'Cancelled') {
                errors.push(message);
            }
            return {
                success: false,
                errors,
                warnings,
                config: this.config as SetupConfig
            };
        }
    }

    /**
     * Step 1: Check Python installation and find/create appropriate environment
     */
    private async checkAndSetupPython(): Promise<{ success: boolean; pythonPath?: string; errors: string[] }> {
        const errors: string[] = [];
        
        // Strategy: Look for existing venv in predictable locations
        const workspaceFolders = vscode.workspace.workspaceFolders;
        const possibleVenvs: string[] = [];

        // Check workspace-relative paths (standard .venv naming only)
        if (workspaceFolders) {
            for (const folder of workspaceFolders) {
                // .venv in workspace root (standard naming)
                possibleVenvs.push(path.join(folder.uri.fsPath, '.venv', 'Scripts', 'python.exe'));
                possibleVenvs.push(path.join(folder.uri.fsPath, '.venv', 'bin', 'python'));
                // ck3raven/.venv (if ck3raven is a subfolder)
                possibleVenvs.push(path.join(folder.uri.fsPath, 'ck3raven', '.venv', 'Scripts', 'python.exe'));
                possibleVenvs.push(path.join(folder.uri.fsPath, 'ck3raven', '.venv', 'bin', 'python'));
            }
        }

        // User home locations
        const userHome = process.env.USERPROFILE || process.env.HOME || '';
        possibleVenvs.push(path.join(userHome, '.ck3raven', '.venv', 'Scripts', 'python.exe'));
        possibleVenvs.push(path.join(userHome, '.ck3raven', '.venv', 'bin', 'python'));

        // Check each possible venv
        for (const venvPython of possibleVenvs) {
            if (fs.existsSync(venvPython)) {
                this.logger.info(`Found Python venv at: ${venvPython}`);
                
                // Verify it actually works
                try {
                    const version = this.getPythonVersion(venvPython);
                    if (version) {
                        this.logger.info(`Python version: ${version}`);
                        return { success: true, pythonPath: venvPython, errors: [] };
                    }
                } catch (e) {
                    this.logger.info(`Python at ${venvPython} failed version check`);
                }
            }
        }

        // No venv found - check system Python
        const systemPythonCandidates = ['python', 'python3', 'py'];
        for (const pythonCmd of systemPythonCandidates) {
            try {
                const version = this.getPythonVersion(pythonCmd);
                if (version) {
                    // System Python found - offer to use it or create venv
                    const choice = await vscode.window.showQuickPick([
                        { label: 'Use system Python', description: `${pythonCmd} (${version})`, value: 'system' },
                        { label: 'Create virtual environment', description: 'Recommended for isolation', value: 'venv' }
                    ], {
                        placeHolder: 'Select Python environment strategy'
                    });

                    if (!choice) {
                        return { success: false, errors: ['Python selection cancelled'] };
                    }

                    if (choice.value === 'system') {
                        return { success: true, pythonPath: pythonCmd, errors: [] };
                    }

                    // Create venv
                    const venvResult = await this.createVirtualEnvironment(pythonCmd);
                    if (venvResult.success) {
                        return { success: true, pythonPath: venvResult.pythonPath, errors: [] };
                    }
                    errors.push(...venvResult.errors);
                }
            } catch (e) {
                // Try next candidate
            }
        }

        errors.push('No Python installation found. Please install Python 3.10+ from https://python.org');
        return { success: false, errors };
    }

    /**
     * Get Python version string
     */
    private getPythonVersion(pythonPath: string): string | null {
        try {
            const result = execSync(`"${pythonPath}" --version`, { encoding: 'utf-8', timeout: 5000 });
            return result.trim();
        } catch {
            return null;
        }
    }

    /**
     * Create a virtual environment
     */
    private async createVirtualEnvironment(systemPython: string): Promise<{ success: boolean; pythonPath?: string; errors: string[] }> {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            return { success: false, errors: ['No workspace folder open'] };
        }

        const venvPath = path.join(workspaceFolders[0].uri.fsPath, '.venv');
        const venvPython = process.platform === 'win32'
            ? path.join(venvPath, 'Scripts', 'python.exe')
            : path.join(venvPath, 'bin', 'python');

        try {
            await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: 'Creating virtual environment...',
                cancellable: false
            }, async () => {
                execSync(`"${systemPython}" -m venv "${venvPath}"`, { timeout: 60000 });
            });

            if (fs.existsSync(venvPython)) {
                return { success: true, pythonPath: venvPython, errors: [] };
            }
            return { success: false, errors: ['Virtual environment creation failed'] };
        } catch (error) {
            return { success: false, errors: [`Failed to create venv: ${error}`] };
        }
    }

    /**
     * Step 2: Detect ck3raven installation path
     */
    private async detectCk3ravenPath(): Promise<{ success: boolean; path?: string; errors: string[] }> {
        const possiblePaths: string[] = [];
        const workspaceFolders = vscode.workspace.workspaceFolders;

        // Check workspace folders for ck3raven
        if (workspaceFolders) {
            for (const folder of workspaceFolders) {
                // ck3raven as subfolder
                possiblePaths.push(path.join(folder.uri.fsPath, 'ck3raven'));
                // This IS the ck3raven folder
                if (folder.uri.fsPath.endsWith('ck3raven') || 
                    fs.existsSync(path.join(folder.uri.fsPath, 'src', 'ck3raven'))) {
                    possiblePaths.unshift(folder.uri.fsPath);
                }
            }
        }

        // Relative to extension installation
        const extensionPath = this.context.extensionPath;
        possiblePaths.push(path.dirname(path.dirname(extensionPath))); // tools/ck3lens-explorer -> ck3raven

        // User home
        const userHome = process.env.USERPROFILE || process.env.HOME || '';
        possiblePaths.push(path.join(userHome, 'ck3raven'));
        possiblePaths.push(path.join(userHome, 'Documents', 'ck3raven'));

        // Check each path for valid ck3raven installation
        for (const checkPath of possiblePaths) {
            if (this.isValidCk3ravenPath(checkPath)) {
                this.logger.info(`Found ck3raven at: ${checkPath}`);
                return { success: true, path: checkPath, errors: [] };
            }
        }

        // Not found - ask user
        const userPath = await vscode.window.showOpenDialog({
            canSelectFiles: false,
            canSelectFolders: true,
            canSelectMany: false,
            openLabel: 'Select ck3raven folder',
            title: 'Locate ck3raven Installation'
        });

        if (userPath && userPath.length > 0) {
            const selectedPath = userPath[0].fsPath;
            if (this.isValidCk3ravenPath(selectedPath)) {
                return { success: true, path: selectedPath, errors: [] };
            }
            return { success: false, errors: [`Selected folder is not a valid ck3raven installation: ${selectedPath}`] };
        }

        return { success: false, errors: ['ck3raven installation not found'] };
    }

    /**
     * Check if a path is a valid ck3raven installation
     */
    private isValidCk3ravenPath(checkPath: string): boolean {
        if (!fs.existsSync(checkPath)) return false;
        
        // Check for key files/folders that indicate ck3raven
        const indicators = [
            path.join(checkPath, 'src', 'ck3raven'),
            path.join(checkPath, 'src', 'ck3raven', '__init__.py'),
            path.join(checkPath, 'tools', 'ck3lens-explorer'),
            path.join(checkPath, 'tools', 'ck3lens_mcp')
        ];

        const found = indicators.filter(p => fs.existsSync(p)).length;
        return found >= 2; // At least 2 indicators present
    }

    /**
     * Step 3: Check and install required Python packages
     */
    private async checkAndInstallPackages(): Promise<{ errors: string[]; warnings: string[] }> {
        const errors: string[] = [];
        const warnings: string[] = [];

        const requiredPackages = [
            { name: 'mcp', minVersion: '0.9.0' },
            { name: 'pydantic', minVersion: '2.0.0' },
            { name: 'sqlite-utils', minVersion: '3.0' }
        ];

        const optionalPackages = [
            { name: 'rich', description: 'Better console output' },
            { name: 'watchdog', description: 'File watching for live reload' }
        ];

        const missingRequired: string[] = [];
        const missingOptional: string[] = [];

        // Check which packages are installed
        for (const pkg of requiredPackages) {
            if (!await this.isPackageInstalled(pkg.name)) {
                missingRequired.push(pkg.name);
            }
        }

        for (const pkg of optionalPackages) {
            if (!await this.isPackageInstalled(pkg.name)) {
                missingOptional.push(pkg.name);
            }
        }

        // Install missing required packages
        if (missingRequired.length > 0) {
            const install = await vscode.window.showWarningMessage(
                `Missing required packages: ${missingRequired.join(', ')}`,
                'Install Now',
                'Cancel'
            );

            if (install === 'Install Now') {
                try {
                    await this.installPackages(missingRequired);
                } catch (error) {
                    errors.push(`Failed to install packages: ${error}`);
                }
            } else {
                errors.push(`Required packages not installed: ${missingRequired.join(', ')}`);
            }
        }

        // Offer to install optional packages
        if (missingOptional.length > 0) {
            warnings.push(`Optional packages not installed: ${missingOptional.join(', ')}`);
        }

        // Also install ck3raven in editable mode if not already
        if (this.config.ck3ravenPath) {
            const ck3ravenInstalled = await this.isPackageInstalled('ck3raven');
            if (!ck3ravenInstalled) {
                try {
                    this.logger.info('Installing ck3raven in editable mode...');
                    await this.runPipCommand(['-e', this.config.ck3ravenPath]);
                } catch (error) {
                    errors.push(`Failed to install ck3raven: ${error}`);
                }
            }
        }

        return { errors, warnings };
    }

    /**
     * Check if a Python package is installed
     */
    private async isPackageInstalled(packageName: string): Promise<boolean> {
        try {
            execSync(`"${this.pythonPath}" -c "import ${packageName.replace('-', '_')}"`, {
                encoding: 'utf-8',
                timeout: 10000
            });
            return true;
        } catch {
            return false;
        }
    }

    /**
     * Install Python packages using pip
     */
    private async installPackages(packages: string[]): Promise<void> {
        return this.runPipCommand(packages);
    }

    /**
     * Run pip install command
     */
    private async runPipCommand(args: string[]): Promise<void> {
        return new Promise((resolve, reject) => {
            const pipArgs = ['-m', 'pip', 'install', ...args];
            this.logger.info(`Running: ${this.pythonPath} ${pipArgs.join(' ')}`);

            const proc = spawn(this.pythonPath, pipArgs, {
                stdio: 'pipe'
            });

            let stderr = '';
            proc.stderr?.on('data', (data) => {
                stderr += data.toString();
            });

            proc.on('close', (code) => {
                if (code === 0) {
                    resolve();
                } else {
                    reject(new Error(`pip install failed: ${stderr}`));
                }
            });

            proc.on('error', (error) => {
                reject(error);
            });
        });
    }

    /**
     * Step 4: Setup game paths (vanilla, workshop, local mods)
     */
    private async setupGamePaths(): Promise<{ success: boolean; errors: string[]; warnings: string[] }> {
        const errors: string[] = [];
        const warnings: string[] = [];

        // Vanilla game path - try to auto-detect
        const vanillaPath = await this.detectOrPromptPath({
            name: 'CK3 Vanilla Game',
            settingKey: 'vanillaPath',
            autoDetectPaths: [
                'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Crusader Kings III\\game',
                'C:\\Program Files\\Steam\\steamapps\\common\\Crusader Kings III\\game',
                path.join(process.env.USERPROFILE || '', 'Steam', 'steamapps', 'common', 'Crusader Kings III', 'game'),
            ],
            validator: (p) => fs.existsSync(path.join(p, 'common')) && fs.existsSync(path.join(p, 'events')),
            isRequired: true,
            promptMessage: 'Select CK3 game folder (contains common/, events/, etc.)'
        });

        if (vanillaPath) {
            this.config.vanillaPath = vanillaPath;
        } else {
            errors.push('CK3 vanilla game path not configured');
        }

        // Steam Workshop path - user must provide
        const workshopPath = await this.detectOrPromptPath({
            name: 'Steam Workshop Mods',
            settingKey: 'workshopPath',
            autoDetectPaths: [
                'C:\\Program Files (x86)\\Steam\\steamapps\\workshop\\content\\1158310',
                'C:\\Program Files\\Steam\\steamapps\\workshop\\content\\1158310',
            ],
            validator: (p) => fs.existsSync(p) && fs.statSync(p).isDirectory(),
            isRequired: false,
            promptMessage: 'Select Steam Workshop mods folder (steamapps/workshop/content/1158310)'
        });

        if (workshopPath) {
            this.config.workshopPath = workshopPath;
        } else {
            warnings.push('Steam Workshop path not configured - workshop mods will not be available');
        }

        // Local mods path - user must provide
        const localModsPath = await this.detectOrPromptPath({
            name: 'Local Mods',
            settingKey: 'modRoot',
            autoDetectPaths: [
                path.join(process.env.USERPROFILE || '', 'Documents', 'Paradox Interactive', 'Crusader Kings III', 'mod'),
            ],
            validator: (p) => fs.existsSync(p) && fs.statSync(p).isDirectory(),
            isRequired: false,
            promptMessage: 'Select local mods folder (Documents/Paradox Interactive/Crusader Kings III/mod)'
        });

        if (localModsPath) {
            this.config.localModsPath = localModsPath;
        } else {
            warnings.push('Local mods path not configured');
        }

        return { success: errors.length === 0, errors, warnings };
    }

    /**
     * Detect or prompt for a path
     */
    private async detectOrPromptPath(options: {
        name: string;
        settingKey: string;
        autoDetectPaths: string[];
        validator: (path: string) => boolean;
        isRequired: boolean;
        promptMessage: string;
    }): Promise<string | null> {
        
        // Check existing setting first
        const existingSetting = vscode.workspace.getConfiguration('ck3lens').get<string>(options.settingKey);
        if (existingSetting && options.validator(existingSetting)) {
            return existingSetting;
        }

        // Try auto-detect paths
        for (const autoPath of options.autoDetectPaths) {
            if (options.validator(autoPath)) {
                this.logger.info(`Auto-detected ${options.name}: ${autoPath}`);
                return autoPath;
            }
        }

        // Prompt user
        const action = options.isRequired ? 'Select' : await vscode.window.showQuickPick(
            ['Select folder', 'Skip (not required)'],
            { placeHolder: `${options.name}: ${options.promptMessage}` }
        );

        if (action === 'Skip (not required)') {
            return null;
        }

        const selected = await vscode.window.showOpenDialog({
            canSelectFiles: false,
            canSelectFolders: true,
            canSelectMany: false,
            openLabel: 'Select',
            title: options.promptMessage
        });

        if (selected && selected.length > 0) {
            const selectedPath = selected[0].fsPath;
            if (options.validator(selectedPath)) {
                return selectedPath;
            }
            vscode.window.showWarningMessage(`Selected path does not appear to be valid for ${options.name}`);
        }

        return null;
    }

    /**
     * Step 5: Setup database path
     */
    private async setupDatabasePath(): Promise<void> {
        // Default to user home .ck3raven folder
        const userHome = process.env.USERPROFILE || process.env.HOME || '';
        const defaultDbDir = path.join(userHome, '.ck3raven');
        const defaultDbPath = path.join(defaultDbDir, 'ck3raven.db');

        // Create directory if it doesn't exist
        if (!fs.existsSync(defaultDbDir)) {
            fs.mkdirSync(defaultDbDir, { recursive: true });
        }

        this.config.databasePath = defaultDbPath;
        this.logger.info(`Database path: ${defaultDbPath}`);
    }

    /**
     * Step 6: Verify the complete setup works
     */
    private async verifySetup(): Promise<{ success: boolean; errors: string[]; warnings: string[] }> {
        const errors: string[] = [];
        const warnings: string[] = [];

        // Test 1: Can we import ck3raven?
        try {
            const importTest = execSync(
                `"${this.pythonPath}" -c "from ck3raven.parser import CK3Parser; print('OK')"`,
                { encoding: 'utf-8', timeout: 10000, cwd: this.config.ck3ravenPath }
            );
            if (!importTest.includes('OK')) {
                errors.push('Failed to import ck3raven parser');
            }
        } catch (error) {
            errors.push(`ck3raven import test failed: ${error}`);
        }

        // Test 2: Can we run the bridge server?
        const bridgePath = path.join(
            this.config.ck3ravenPath || '',
            'tools', 'ck3lens-explorer', 'bridge', 'server.py'
        );
        if (!fs.existsSync(bridgePath)) {
            errors.push(`Bridge server not found at: ${bridgePath}`);
        }

        // Test 3: Check vanilla path has expected structure
        if (this.config.vanillaPath) {
            const expectedFolders = ['common', 'events', 'localization'];
            for (const folder of expectedFolders) {
                if (!fs.existsSync(path.join(this.config.vanillaPath, folder))) {
                    warnings.push(`Vanilla path missing expected folder: ${folder}`);
                }
            }
        }

        return { success: errors.length === 0, errors, warnings };
    }

    /**
     * Step 7: Save configuration to VS Code settings
     */
    private async saveConfiguration(): Promise<void> {
        const config = vscode.workspace.getConfiguration('ck3lens');
        
        // Determine scope - prefer workspace if available
        const target = vscode.workspace.workspaceFolders 
            ? vscode.ConfigurationTarget.Workspace 
            : vscode.ConfigurationTarget.Global;

        if (this.config.pythonPath) {
            await config.update('pythonPath', this.config.pythonPath, target);
        }
        if (this.config.ck3ravenPath) {
            await config.update('ck3ravenPath', this.config.ck3ravenPath, target);
        }
        if (this.config.databasePath) {
            await config.update('databasePath', this.config.databasePath, target);
        }
        if (this.config.vanillaPath) {
            await config.update('vanillaPath', this.config.vanillaPath, target);
        }
        if (this.config.localModsPath) {
            await config.update('modRoot', this.config.localModsPath, target);
        }

        this.logger.info('Configuration saved successfully');
    }

    /**
     * Quick diagnostic check - runs without prompts
     */
    async runDiagnostics(): Promise<DependencyCheck[]> {
        const checks: DependencyCheck[] = [];

        // Python check - for diagnostics, we DO check system python since we're
        // trying to determine what's available. This is intentionally different
        // from runtime code which must NEVER fall back to bare 'python'.
        let pythonToCheck = this.pythonPath;
        if (!pythonToCheck) {
            // Try to find venv first
            const ck3ravenPath = vscode.workspace.getConfiguration('ck3lens').get<string>('ck3ravenPath') || '';
            const venvPaths = [
                path.join(ck3ravenPath, '.venv', 'Scripts', 'python.exe'),
                path.join(ck3ravenPath, '.venv', 'bin', 'python'),
            ];
            for (const venvPython of venvPaths) {
                if (fs.existsSync(venvPython)) {
                    pythonToCheck = venvPython;
                    break;
                }
            }
        }
        // For diagnostics only, fall back to checking system python existence
        if (!pythonToCheck) {
            pythonToCheck = 'python';
        }
        
        const pythonVersion = this.getPythonVersion(pythonToCheck);
        const isSystemPython = pythonToCheck === 'python';
        checks.push({
            name: 'Python',
            status: pythonVersion ? 'ok' : 'missing',
            version: pythonVersion || undefined,
            message: pythonVersion 
                ? (isSystemPython ? 'Using system Python (recommend venv)' : undefined)
                : 'Python not found - run setup wizard',
            canAutoInstall: false
        });

        // Required packages
        const packages = ['mcp', 'pydantic', 'sqlite_utils', 'ck3raven'];
        for (const pkg of packages) {
            const installed = await this.isPackageInstalled(pkg);
            checks.push({
                name: pkg,
                status: installed ? 'ok' : 'missing',
                message: installed ? undefined : `Package ${pkg} not installed`,
                canAutoInstall: true
            });
        }

        return checks;
    }
}

/**
 * Quick setup check command - shows status without running full wizard
 */
export async function showSetupStatus(context: vscode.ExtensionContext, logger: Logger): Promise<void> {
    const wizard = new SetupWizard(context, logger);
    const diagnostics = await wizard.runDiagnostics();

    const items: vscode.QuickPickItem[] = diagnostics.map(d => ({
        label: `${d.status === 'ok' ? '✅' : '❌'} ${d.name}`,
        description: d.version || d.message,
        detail: d.canAutoInstall && d.status !== 'ok' ? 'Can be auto-installed' : undefined
    }));

    items.push({ label: '', kind: vscode.QuickPickItemKind.Separator });
    items.push({ label: '🔧 Run Setup Wizard', description: 'Configure CK3 Lens' });

    const selected = await vscode.window.showQuickPick(items, {
        placeHolder: 'CK3 Lens Setup Status',
        title: 'Dependencies & Configuration'
    });

    if (selected?.label === '🔧 Run Setup Wizard') {
        await wizard.run();
    }
}
