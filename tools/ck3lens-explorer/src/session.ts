/**
 * CK3 Lens Session - Manages connection to ck3raven database
 */

import * as vscode from 'vscode';
import { PythonBridge } from './bridge/pythonBridge';
import { Logger } from './utils/logger';

export interface SessionInfo {
    modRoot: string;
    liveMods: LiveModInfo[];
    dbPath: string;
    playsetId: number;
    playsetName: string | null;
}

export interface LiveModInfo {
    modId: string;
    name: string;
    path: string;
    exists: boolean;
}

export interface SymbolResult {
    name: string;
    symbolType: string;
    fileId: number;
    relpath: string;
    line: number;
    mod: string;
}

export interface ConflictInfo {
    name: string;
    symbolType: string;
    folder: string;
    winner: {
        mod: string;
        file: string;
        line: number;
    };
    losers: Array<{
        mod: string;
        file: string;
        line: number;
    }>;
}

export interface FileInfo {
    fileId: number;
    relpath: string;
    mod: string;
    size: number;
    content?: string;
}

export interface PlaysetModInfo {
    name: string;
    contentVersionId: number;
    loadOrder: number;
    kind: string;
    fileCount: number;
    sourcePath?: string;
}

export interface FolderInfo {
    name: string;
    fileCount: number;
}

export interface FolderContents {
    folders: FolderInfo[];
    files: Array<{
        relpath: string;
        modName?: string;
        contentHash?: string;
        fileType?: string;
        absPath?: string;
    }>;
}

export interface ExplorerFilter {
    folderPattern?: string;
    textSearch?: string;
    symbolSearch?: string;
    modFilter?: string[];
    fileTypeFilter?: string[];
}

export class CK3LensSession implements vscode.Disposable {
    private _initialized: boolean = false;
    private _sessionInfo: SessionInfo | null = null;

    constructor(
        private readonly pythonBridge: PythonBridge,
        private readonly logger: Logger
    ) {}

    /**
     * Check if session is initialized
     */
    get isInitialized(): boolean {
        return this._initialized;
    }

    /**
     * Get session info
     */
    get sessionInfo(): SessionInfo | null {
        return this._sessionInfo;
    }

    /**
     * Initialize the session - connect to ck3raven database
     */
    async initialize(): Promise<void> {
        this.logger.info('Initializing CK3 Lens session...');

        try {
            const config = vscode.workspace.getConfiguration('ck3lens');
            const dbPath = config.get<string>('databasePath') || undefined;
            const liveMods = config.get<string[]>('liveMods') || undefined;

            const result = await this.pythonBridge.call('init_session', {
                db_path: dbPath,
                live_mods: liveMods
            });

            this._sessionInfo = {
                modRoot: result.mod_root,
                liveMods: result.live_mods?.mods || [],
                dbPath: result.db_path,
                playsetId: result.playset_id,
                playsetName: result.playset_name
            };

            this._initialized = true;
            this.logger.info(`Session initialized: ${this._sessionInfo.dbPath}`);
            this.logger.info(`Live mods: ${this._sessionInfo.liveMods.map(m => m.name).join(', ')}`);

        } catch (error) {
            this._initialized = false;
            this.logger.error('Failed to initialize session', error);
            throw error;
        }
    }

    /**
     * Search for symbols in the database
     */
    async searchSymbols(query: string, symbolType?: string, limit: number = 50): Promise<SymbolResult[]> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('search_symbols', {
                query,
                symbol_type: symbolType,
                limit,
                adjacency: 'auto'
            });

            return result.results?.results || [];
        } catch (error) {
            this.logger.error('Symbol search failed', error);
            return [];
        }
    }

    /**
     * Confirm a symbol does NOT exist (exhaustive search)
     */
    async confirmNotExists(name: string, symbolType?: string): Promise<{
        canClaim: boolean;
        similarMatches: SymbolResult[];
    }> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('confirm_not_exists', {
                name,
                symbol_type: symbolType
            });

            return {
                canClaim: result.can_claim_not_exists,
                similarMatches: result.similar_matches || []
            };
        } catch (error) {
            this.logger.error('Confirm not exists failed', error);
            return { canClaim: false, similarMatches: [] };
        }
    }

    /**
     * Get file content from database
     */
    async getFile(filePath: string, includeAst: boolean = false): Promise<FileInfo | null> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('get_file', {
                file_path: filePath,
                include_ast: includeAst
            });

            return result;
        } catch (error) {
            this.logger.error('Get file failed', error);
            return null;
        }
    }

    /**
     * Get conflicts for a folder or symbol type
     */
    async getConflicts(pathPattern?: string, symbolType?: string): Promise<ConflictInfo[]> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('get_conflicts', {
                path_pattern: pathPattern,
                symbol_type: symbolType
            });

            return result.conflicts || [];
        } catch (error) {
            this.logger.error('Get conflicts failed', error);
            return [];
        }
    }

    /**
     * List files in a folder
     */
    async listFiles(folder: string, pattern: string = '*.txt'): Promise<FileInfo[]> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('list_files', {
                folder,
                pattern
            });

            return result.files || [];
        } catch (error) {
            this.logger.error('List files failed', error);
            return [];
        }
    }

    /**
     * Get mods in the active playset with load order
     */
    async getPlaysetMods(): Promise<PlaysetModInfo[]> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('get_playset_mods', {});
            return result.mods || [];
        } catch (error) {
            this.logger.error('Get playset mods failed', error);
            return [];
        }
    }

    /**
     * Get top-level folders across all mods in playset
     */
    async getTopLevelFolders(): Promise<FolderInfo[]> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('get_top_level_folders', {});
            return result.folders || [];
        } catch (error) {
            this.logger.error('Get top level folders failed', error);
            return [];
        }
    }

    /**
     * Get folders within a specific mod's content version
     */
    async getModFolders(contentVersionId: number): Promise<FolderInfo[]> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('get_mod_folders', {
                content_version_id: contentVersionId
            });
            return result.folders || [];
        } catch (error) {
            this.logger.error('Get mod folders failed', error);
            return [];
        }
    }

    /**
     * Get contents of a folder - subfolders and files
     */
    async getFolderContents(
        path: string,
        contentVersionId?: number,
        filter?: ExplorerFilter
    ): Promise<FolderContents> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('get_folder_contents', {
                path,
                content_version_id: contentVersionId,
                folder_pattern: filter?.folderPattern,
                text_search: filter?.textSearch,
                symbol_search: filter?.symbolSearch,
                mod_filter: filter?.modFilter,
                file_type_filter: filter?.fileTypeFilter
            });
            return {
                folders: result.folders || [],
                files: result.files || []
            };
        } catch (error) {
            this.logger.error('Get folder contents failed', error);
            return { folders: [], files: [] };
        }
    }

    /**
     * Get list of live (writable) mods
     */
    async getLiveMods(): Promise<LiveModInfo[]> {
        if (!this._initialized) {
            await this.initialize();
        }

        try {
            const result = await this.pythonBridge.call('list_live_mods', {});
            return result.live_mods?.mods || [];
        } catch (error) {
            this.logger.error('Get live mods failed', error);
            return [];
        }
    }

    /**
     * Read file from live mod (current disk state)
     */
    async readLiveFile(modName: string, relPath: string): Promise<string | null> {
        try {
            const result = await this.pythonBridge.call('read_live_file', {
                mod_name: modName,
                rel_path: relPath
            });

            return result.content;
        } catch (error) {
            this.logger.error('Read live file failed', error);
            return null;
        }
    }

    /**
     * Write file to live mod
     */
    async writeLiveFile(modName: string, relPath: string, content: string): Promise<boolean> {
        try {
            const result = await this.pythonBridge.call('write_file', {
                mod_name: modName,
                rel_path: relPath,
                content,
                validate_syntax: true
            });

            return result.success;
        } catch (error) {
            this.logger.error('Write live file failed', error);
            return false;
        }
    }

    /**
     * Parse content and return AST or errors
     */
    async parseContent(content: string, filename?: string): Promise<{
        success: boolean;
        ast?: any;
        errors?: Array<{ line: number; message: string }>;
    }> {
        try {
            const result = await this.pythonBridge.call('parse_content', {
                content,
                filename: filename || 'inline.txt'
            });

            return {
                success: !result.errors || result.errors.length === 0,
                ast: result.ast,
                errors: result.errors
            };
        } catch (error) {
            this.logger.error('Parse content failed', error);
            return {
                success: false,
                errors: [{ line: 1, message: String(error) }]
            };
        }
    }

    /**
     * Validate a PatchDraft contract
     */
    async validatePatchDraft(patchDraft: any): Promise<{
        valid: boolean;
        errors: string[];
        warnings: string[];
    }> {
        try {
            const result = await this.pythonBridge.call('validate_patchdraft', {
                patchdraft: patchDraft
            });

            return {
                valid: result.errors?.length === 0,
                errors: result.errors || [],
                warnings: result.warnings || []
            };
        } catch (error) {
            this.logger.error('Validate patch draft failed', error);
            return {
                valid: false,
                errors: [String(error)],
                warnings: []
            };
        }
    }

    /**
     * Get git status for a live mod
     */
    async getGitStatus(modName: string): Promise<{
        staged: string[];
        unstaged: string[];
        untracked: string[];
    } | null> {
        try {
            const result = await this.pythonBridge.call('git_status', {
                mod_name: modName
            });

            return result;
        } catch (error) {
            this.logger.error('Git status failed', error);
            return null;
        }
    }

    dispose(): void {
        this._initialized = false;
        this._sessionInfo = null;
    }
}
