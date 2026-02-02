/**
 * Manifest Writer
 * 
 * Writes manifest.json for journal windows.
 * 
 * INVARIANT JRN-VIS-001: Manifest MUST be written even on total failure.
 * "If it happened, it must be visible."
 */

import * as fs from 'fs';
import * as path from 'path';
import { 
    Manifest, 
    ManifestExport, 
    ManifestTelemetry, 
    ManifestError,
    CloseReason,
    MANIFEST_VERSION,
    EXTRACTOR_VERSION,
} from './types';
import { getManifestPath, enforceJournalsBoundary } from './storage';
import { StructuredLogger } from '../utils/structuredLogger';

/**
 * Create an empty telemetry object.
 */
export function createEmptyTelemetry(): ManifestTelemetry {
    return {
        sessions_scanned: 0,
        sessions_changed: 0,
        sessions_exported: 0,
        duplicates_skipped: 0,
        extraction_duration_ms: 0,
    };
}

/**
 * Create a manifest object.
 * 
 * @param windowId - Window identifier
 * @param workspaceKey - Workspace key
 * @param startedAt - Window start time (ISO 8601)
 * @param closedAt - Window close time (ISO 8601)
 * @param closeReason - Reason for window close
 * @param exports - Exported sessions
 * @param telemetry - Extraction telemetry
 * @param errors - Errors encountered
 */
export function createManifest(
    windowId: string,
    workspaceKey: string,
    startedAt: string,
    closedAt: string,
    closeReason: CloseReason,
    exports: ManifestExport[],
    telemetry: ManifestTelemetry,
    errors: ManifestError[]
): Manifest {
    return {
        manifest_version: MANIFEST_VERSION,
        extractor_version: EXTRACTOR_VERSION,
        window_id: windowId,
        workspace_key: workspaceKey,
        started_at: startedAt,
        closed_at: closedAt,
        close_reason: closeReason,
        exports,
        telemetry,
        errors,
    };
}

/**
 * Write manifest to disk.
 * 
 * INVARIANT JRN-VIS-001: This function MUST NOT throw.
 * On any error, it writes an error manifest instead.
 * 
 * @param manifest - Manifest to write
 * @param outputPath - Window output directory
 * @param logger - Structured logger
 * @returns true if write succeeded, false if error manifest was written
 */
export function writeManifest(
    manifest: Manifest,
    outputPath: string,
    logger: StructuredLogger
): boolean {
    const manifestPath = path.join(outputPath, 'manifest.json');
    
    try {
        // Enforce boundary
        enforceJournalsBoundary(manifestPath, logger);
        
        // Write manifest
        const content = JSON.stringify(manifest, null, 2);
        fs.writeFileSync(manifestPath, content, 'utf-8');
        
        logger.debug('ext.journal.manifest', 'Manifest written', {
            window_id: manifest.window_id,
            exports_count: manifest.exports.length,
            errors_count: manifest.errors.length,
        });
        
        return true;
    } catch (err) {
        // INVARIANT JRN-VIS-001: Must still write manifest on error
        logger.error('ext.journal.manifest', 'Failed to write manifest, attempting error manifest', {
            error: (err as Error).message,
            window_id: manifest.window_id,
        });
        
        try {
            // Create error manifest
            const errorManifest: Manifest = {
                ...manifest,
                exports: [],
                errors: [
                    ...manifest.errors,
                    {
                        code: 'JRN-MAN-E-001',
                        message: `Manifest write failed: ${(err as Error).message}`,
                        stack: (err as Error).stack?.substring(0, 500),
                    }
                ],
            };
            
            const content = JSON.stringify(errorManifest, null, 2);
            fs.writeFileSync(manifestPath, content, 'utf-8');
            
            logger.warn('ext.journal.manifest', 'Error manifest written', {
                window_id: manifest.window_id,
            });
        } catch (innerErr) {
            // Final fallback: log to structured logger
            logger.error('ext.journal.manifest', 'CRITICAL: Could not write any manifest', {
                window_id: manifest.window_id,
                outer_error: (err as Error).message,
                inner_error: (innerErr as Error).message,
            });
        }
        
        return false;
    }
}

/**
 * Read a manifest from disk.
 * 
 * @param workspaceKey - Workspace identifier
 * @param windowId - Window identifier
 * @returns Manifest or null if not found/invalid
 */
export function readManifest(workspaceKey: string, windowId: string): Manifest | null {
    const manifestPath = getManifestPath(workspaceKey, windowId);
    
    try {
        if (!fs.existsSync(manifestPath)) {
            return null;
        }
        
        const content = fs.readFileSync(manifestPath, 'utf-8');
        const manifest = JSON.parse(content) as Manifest;
        
        // Basic validation
        if (manifest.manifest_version !== MANIFEST_VERSION) {
            console.warn(`Manifest version mismatch: ${manifest.manifest_version}`);
        }
        
        return manifest;
    } catch {
        return null;
    }
}

/**
 * Create a ManifestExport entry.
 */
export function createManifestExport(
    sessionId: string,
    fingerprint: string,
    tags: string[]
): ManifestExport {
    return {
        session_id: sessionId,
        fingerprint,
        json_path: `${sessionId}.json`,
        md_path: `${sessionId}.md`,
        tags,
    };
}

/**
 * Create a ManifestError from an exception.
 */
export function createManifestError(
    code: string,
    err: Error,
    sessionId?: string
): ManifestError {
    return {
        code,
        message: err.message,
        session_id: sessionId,
        stack: err.stack?.substring(0, 500),
    };
}
