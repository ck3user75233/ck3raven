/**
 * Journal Extractor Type Definitions
 * 
 * Core interfaces for the Journal Extractor subsystem.
 * See docs/JOURNAL_EXTRACTOR_SPEC.md for full specification.
 */

// ============================================================================
// Manifest Schema v2.0
// ============================================================================

/**
 * Exported session entry in manifest.
 */
export interface ManifestExport {
    /** Session identifier from Copilot Chat */
    session_id: string;
    
    /** SHA-256 fingerprint for deduplication */
    fingerprint: string;
    
    /** Relative path to raw JSON export */
    json_path: string;
    
    /** Relative path to Markdown export */
    md_path: string;
    
    /** Extracted tags (e.g., "*tag:architecture*") */
    tags: string[];
}

/**
 * Telemetry data for the extraction run.
 */
export interface ManifestTelemetry {
    /** Total sessions scanned */
    sessions_scanned: number;
    
    /** Sessions with changes detected */
    sessions_changed: number;
    
    /** Sessions successfully exported */
    sessions_exported: number;
    
    /** Sessions skipped due to duplicate fingerprint */
    duplicates_skipped: number;
    
    /** Time spent on extraction in milliseconds */
    extraction_duration_ms: number;
    
    /** FR-3: Number of MCP tool calls captured in trace */
    tool_calls_captured?: number;
}

/**
 * Error entry for manifest errors array.
 */
export interface ManifestError {
    /** Error code (JRN-* format) */
    code: string;
    
    /** Human-readable error message */
    message: string;
    
    /** Optional session ID if error is session-specific */
    session_id?: string;
    
    /** Optional stack trace for debugging */
    stack?: string;
}

/**
 * Manifest v2.0 schema.
 * 
 * INVARIANT JRN-VIS-001: Manifest MUST be written even on total failure.
 * If extraction fails, exports will be empty and errors will contain failure details.
 */
export interface Manifest {
    /** Schema version - always "2.0" */
    manifest_version: '2.0';
    
    /** Extractor version (semver) */
    extractor_version: string;
    
    /** Unique window identifier (ISO timestamp + counter) */
    window_id: string;
    
    /** Workspace key (SHA-256 hash of normalized path) */
    workspace_key: string;
    
    /** Window start time (ISO 8601 UTC) */
    started_at: string;
    
    /** Window close time (ISO 8601 UTC) */
    closed_at: string;
    
    /** Reason for window close */
    close_reason: CloseReason;
    
    /** Exported sessions */
    exports: ManifestExport[];
    
    /** Extraction telemetry */
    telemetry: ManifestTelemetry;
    
    /** Errors encountered (always present, empty array if none) */
    errors: ManifestError[];
}

// ============================================================================
// Window State
// ============================================================================

/**
 * Reasons a window can be closed.
 */
export type CloseReason = 
    | 'user_command'        // User explicitly closed
    | 'overlap_new_window'  // New window started, auto-closed previous
    | 'deactivate';         // Extension deactivating

/**
 * State of an active journal window.
 */
export interface WindowState {
    /** Unique window identifier */
    window_id: string;
    
    /** Workspace key this window is scoped to */
    workspace_key: string;
    
    /** Window start time (ISO 8601 UTC) */
    started_at: string;
    
    /** Baseline snapshot (mtime/size per file path) */
    baseline: BaselineSnapshot;
    
    /** Path to discovered chatSessions directory */
    chatSessionsPath: string;
    
    /** Output directory for this window */
    outputPath: string;
}

/**
 * Baseline snapshot of file states at window start.
 * Key is absolute file path, value is FileState.
 */
export type BaselineSnapshot = Map<string, FileState>;

/**
 * State of a single file for baseline comparison.
 */
export interface FileState {
    /** Last modification time (Unix epoch ms) */
    mtime: number;
    
    /** File size in bytes */
    size: number;
}

// ============================================================================
// Session Metadata
// ============================================================================

/**
 * Metadata extracted from a Copilot Chat session.
 */
export interface SessionMetadata {
    /** Session identifier from Copilot Chat */
    session_id: string;
    
    /** File path to the session JSON */
    file_path: string;
    
    /** Last modification time */
    mtime: number;
    
    /** File size */
    size: number;
    
    /** SHA-256 fingerprint (computed on extraction) */
    fingerprint?: string;
    
    /** Extracted tags */
    tags?: string[];
}

// ============================================================================
// Discovery
// ============================================================================

/**
 * Candidate root for chatSessions discovery.
 */
export interface CandidateRoot {
    /** Absolute path to candidate directory */
    path: string;
    
    /** Source of this candidate */
    source: CandidateSource;
    
    /** Ranking score (higher = better match) */
    score: number;
}

/**
 * Source types for candidate roots (scan order).
 */
export type CandidateSource =
    | 'api_context'     // From globalStorageUri neighbor scan
    | 'standard_local'  // Platform-specific standard paths
    | 'remote_server';  // SSH, WSL, Dev Container

/**
 * Result of discovery process.
 */
export interface DiscoveryResult {
    /** Whether a valid chatSessions directory was found */
    success: boolean;
    
    /** Path to chatSessions directory (if found) */
    chatSessionsPath?: string;
    
    /** All candidates evaluated with their scores */
    candidates: CandidateRoot[];
    
    /** Error code if discovery failed (e.g., JRN-DISC-E-001) */
    error?: string;
    
    /** Human-readable error message */
    errorMessage?: string;
}

// ============================================================================
// Extraction
// ============================================================================

/**
 * Result of delta detection.
 */
export interface DeltaResult {
    /** Files that were added since baseline */
    added: string[];
    
    /** Files that were modified since baseline */
    modified: string[];
    
    /** Files that were deleted since baseline */
    deleted: string[];
}

/**
 * Result of session extraction.
 */
export interface ExtractionResult {
    /** Whether extraction succeeded */
    success: boolean;
    
    /** Exported session metadata */
    exports: ManifestExport[];
    
    /** Telemetry data */
    telemetry: ManifestTelemetry;
    
    /** Errors encountered */
    errors: ManifestError[];
}

// ============================================================================
// Configuration
// ============================================================================

/**
 * Journal Extractor configuration.
 */
export interface JournalConfig {
    /** Base path for journal storage */
    journalsPath: string;
    
    /** Workspace key override (if set via config) */
    workspaceKeyOverride?: string;
    
    /** Time bucket for fingerprinting in seconds (default: 60) */
    timeBucketSeconds: number;
}

/**
 * Default configuration values.
 */
export const DEFAULT_CONFIG: Readonly<JournalConfig> = {
    journalsPath: '', // Set at runtime to ~/.ck3raven/journals/
    timeBucketSeconds: 60,
};

// ============================================================================
// Constants
// ============================================================================

/** Current extractor version */
export const EXTRACTOR_VERSION = '1.0.0';

/** Manifest schema version */
export const MANIFEST_VERSION = '2.0' as const;

/** Log category prefix */
export const LOG_CATEGORY_PREFIX = 'ext.journal';

/** Log categories per spec */
export const LOG_CATEGORIES = {
    WINDOW_START: 'ext.journal.window_start',
    WINDOW_END: 'ext.journal.window_end',
    DISCOVERY: 'ext.journal.discovery',
    EXTRACTION: 'ext.journal.extraction',
    DELTA: 'ext.journal.delta',
    TAG_INDEX: 'ext.journal.tag_index',
    ACCESS_DENIED: 'ext.journal.access_denied',
    STORAGE_LOCKED: 'ext.journal.storage_locked',
} as const;
