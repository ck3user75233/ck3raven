/**
 * Fingerprint Algorithm
 * 
 * Implements v3.1 deduplication fingerprinting.
 * 
 * Fingerprint = SHA-256( Canonical_Role + Canonical_Text + Attachment_Hash + Time_Bucket )
 * 
 * - Canonical Role: user | assistant (lowercase)
 * - Canonical Text: Trimmed, normalized whitespace
 * - Attachment Hash: Sorted list of attachment URIs joined by |
 * - Time Bucket: Timestamp rounded down to nearest 60 seconds
 */

import * as crypto from 'crypto';
import { CopilotMessage, CopilotSession } from './backends/jsonBackend';

/** Time bucket size in milliseconds (60 seconds per spec) */
const TIME_BUCKET_MS = 60 * 1000;

/**
 * Compute fingerprint for a single message.
 * 
 * @param message - The message to fingerprint
 * @param timeBucketSeconds - Time bucket size (default 60s)
 * @returns SHA-256 hex string
 */
export function fingerprintMessage(
    message: CopilotMessage,
    timeBucketSeconds: number = 60
): string {
    const hash = crypto.createHash('sha256');
    
    // 1. Canonical Role (lowercase)
    const role = message.role.toLowerCase();
    hash.update(role);
    hash.update('\x00'); // Null separator
    
    // 2. Canonical Text (trimmed, normalized whitespace)
    const text = normalizeText(message.content);
    hash.update(text);
    hash.update('\x00');
    
    // 3. Attachment Hash (sorted URIs joined by |)
    const attachmentHash = computeAttachmentHash(message.attachments);
    hash.update(attachmentHash);
    hash.update('\x00');
    
    // 4. Time Bucket (floor to time bucket size)
    const bucketMs = timeBucketSeconds * 1000;
    const timestamp = message.timestamp ?? 0;
    const timeBucket = Math.floor(timestamp / bucketMs) * bucketMs;
    hash.update(String(timeBucket));
    
    return hash.digest('hex');
}

/**
 * Compute fingerprint for an entire session.
 * 
 * This is a combined fingerprint of all messages in order.
 * 
 * @param session - The session to fingerprint
 * @returns SHA-256 hex string
 */
export function fingerprintSession(session: CopilotSession): string {
    const hash = crypto.createHash('sha256');
    
    // Hash each message in order
    for (const message of session.messages) {
        const msgFingerprint = fingerprintMessage(message);
        hash.update(msgFingerprint);
        hash.update('\x00');
    }
    
    return hash.digest('hex');
}

/**
 * Normalize text for fingerprinting.
 * 
 * - Trim whitespace
 * - Collapse multiple whitespace to single space
 * - Normalize line endings
 */
function normalizeText(text: string): string {
    return text
        .trim()
        .replace(/\r\n/g, '\n')  // Normalize line endings
        .replace(/\s+/g, ' ');    // Collapse whitespace
}

/**
 * Compute hash component from attachments.
 * 
 * - Extract URIs from attachments
 * - Sort alphabetically
 * - Join with |
 */
function computeAttachmentHash(attachments?: { uri?: string }[]): string {
    if (!attachments || attachments.length === 0) {
        return '';
    }
    
    const uris = attachments
        .map(a => a.uri ?? '')
        .filter(uri => uri.length > 0)
        .sort();
    
    return uris.join('|');
}

/**
 * Check if two fingerprints match.
 */
export function fingerprintMatch(fp1: string, fp2: string): boolean {
    return fp1.toLowerCase() === fp2.toLowerCase();
}

/**
 * Create a fingerprint display string (first 16 chars).
 */
export function fingerprintShort(fingerprint: string): string {
    return fingerprint.substring(0, 16);
}
