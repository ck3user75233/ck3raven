/**
 * Journal Extractor Module
 * 
 * Main entry point for the Journal Extractor subsystem.
 * 
 * See docs/JOURNAL_EXTRACTOR_SPEC.md for full specification.
 * See docs/JOURNAL_IMPLEMENTATION_PLAN.md for implementation details.
 */

// Types
export * from './types';

// Workspace identity
export { 
    deriveWorkspaceKey,
    deriveActiveWorkspaceKey,
    getWorkspaceDisplayName,
} from './workspaceKey';

// Discovery
export {
    discoverChatSessions,
    validateChatSessionsPath,
} from './discovery';

// Storage
export {
    getJournalsBasePath,
    getWorkspaceJournalPath,
    getWindowsPath,
    getIndexPath,
    getWindowPath,
    getManifestPath,
    getTagsIndexPath,
    initializeStorage,
    initializeWindow,
    isWithinJournals,
    enforceJournalsBoundary,
    generateWindowId,
    listWindows,
    getDefaultConfig,
    getJournalBasePath,
} from './storage';

// Baseline & Delta
export { createBaseline, serializeBaseline, deserializeBaseline } from './baseline';
export { detectDelta, getChangedFiles, hasChanges } from './delta';

// Window Manager
export { 
    WindowManager, 
    initializeWindowManager, 
    getWindowManager,
    getIsShuttingDown,
    setShuttingDown,
    getPendingMarkerPath,
    type PendingExtractionMarker,
} from './windowManager';

// Startup Extractor (Phase 1 - copy-then-read)
export {
    runStartupExtraction,
    scheduleStartupExtraction,
} from './startupExtractor';

// Commands
export { registerJournalCommands, JOURNAL_COMMANDS } from './commands';

// Status Bar
export { JournalStatusBar, createJournalStatusBar } from './statusBar';

// Backends
export { parseSessionFile, CopilotSession, CopilotMessage } from './backends/jsonBackend';

// Extraction
export { extractWindow } from './extractor';
export { fingerprintMessage, fingerprintSession } from './fingerprint';
export { extractTagsFromSession, createTagIndexEntries, TagIndexEntry } from './tagScraper';
export { sessionToMarkdown } from './markdownExport';
export { 
    createManifest, 
    createEmptyTelemetry, 
    createManifestExport, 
    createManifestError,
    writeManifest,
} from './manifest';

// Indexing (note: listWindows is from storage, these are indexer-specific)
export {
    readTagIndex,
    searchTags,
    getUniqueTags,
    getTagStats,
    getSessionTags,
    getWindowTags,
    rebuildTagIndex,
    listWorkspaces,
} from './indexer';

// FR-3: Trace Reader
export {
    readTraceEvents,
    readToolCalls,
    formatTraceAsMarkdown,
    traceFileExists,
    cleanupOldTraceFiles,
    getTraceFilePath,
    summarizeToolUsage,
    type ToolCallEvent,
    type SessionStartEvent,
    type AnyTraceEvent,
} from './traceReader';
