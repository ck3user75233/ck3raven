#!/usr/bin/env python3
"""
Block-based logging system for the builder daemon.

Blocks are batches of files processed together, identified by Merkle hashes.
Each block has aggregated metrics for files, bytes, timing, and errors.

See docs/BLOCK_LOGGING_DESIGN_v1.0.md for full architecture.
"""

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Literal, Optional

# Type alias for file processing status
FileStatus = Literal["processed", "uptodate", "error", "ignored"]

# Block thresholds - close block when either is reached
FILE_THRESHOLD = 500  # Max files per block
BYTE_THRESHOLD = 50 * 1024 * 1024  # 50MB max bytes scanned per block


@dataclass(frozen=True)
class BlockLog:
    """Immutable record of a completed block.
    
    A block represents a batch of files processed together during a build phase.
    Once created, block records are never modified - they form an audit trail.
    """
    
    # Identity
    block_id: str              # UUID for this block (e.g., "blk-a1b2c3d4")
    build_id: str              # Parent build UUID
    phase: str                 # e.g., "ingest", "ast_generation", "symbol_extraction"
    block_number: int          # Sequence within phase (1, 2, 3...)
    
    # Timing
    started_at: str            # ISO8601 timestamp
    ended_at: str              # ISO8601 timestamp
    duration_sec: float        # Elapsed seconds
    
    # File Metrics
    files_scanned: int         # Total files examined
    files_processed: int       # Files that produced output
    files_skipped_uptodate: int  # Skipped (hash unchanged)
    files_skipped_error: int   # Skipped (parse/read error)
    files_skipped_ignored: int # Skipped (not in scope, e.g., .dds)
    
    # Byte Metrics
    bytes_scanned: int         # Total bytes read from disk
    bytes_stored: int          # Bytes written to DB (AST blobs, etc.)
    
    # Integrity
    block_hash: str            # Merkle root of file hashes in block
    
    # Error Manifest (JSON string for storage)
    error_manifest: Optional[str] = None  # JSON: [{path, error_type, message}]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BlockLog":
        """Create from database row."""
        return cls(
            block_id=row["block_id"],
            build_id=row["build_id"],
            phase=row["phase"],
            block_number=row["block_number"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_sec=row["duration_sec"],
            files_scanned=row["files_scanned"],
            files_processed=row["files_processed"],
            files_skipped_uptodate=row["files_skipped_uptodate"],
            files_skipped_error=row["files_skipped_error"],
            files_skipped_ignored=row["files_skipped_ignored"],
            bytes_scanned=row["bytes_scanned"],
            bytes_stored=row["bytes_stored"],
            block_hash=row["block_hash"],
            error_manifest=row["error_manifest"],
        )
    
    @property
    def throughput_files_sec(self) -> float:
        """Files processed per second."""
        if self.duration_sec <= 0:
            return 0.0
        return self.files_scanned / self.duration_sec
    
    @property
    def throughput_mb_sec(self) -> float:
        """Megabytes scanned per second."""
        if self.duration_sec <= 0:
            return 0.0
        return (self.bytes_scanned / (1024 * 1024)) / self.duration_sec
    
    @property
    def error_count(self) -> int:
        """Number of errors in this block."""
        return self.files_skipped_error
    
    def format_summary(self) -> str:
        """Format a one-line summary for status display."""
        status = "✓" if self.error_count == 0 else f"{self.error_count} errors"
        mb_scanned = self.bytes_scanned / (1024 * 1024)
        return (
            f"#{self.block_number:3d} | {self.phase:20s} | "
            f"{self.files_scanned:4d} files | {mb_scanned:6.1f}MB | "
            f"{self.duration_sec:5.1f}s | {self.throughput_files_sec:5.1f} files/s | {status}"
        )


@dataclass
class StageSummary:
    """Aggregated metrics for an entire phase.
    
    Created by aggregating all BlockLog records for a phase.
    """
    
    phase: str
    build_id: str
    total_blocks: int
    
    # Aggregated metrics
    total_files_scanned: int
    total_files_processed: int
    total_files_skipped_uptodate: int
    total_files_skipped_error: int
    total_files_skipped_ignored: int
    total_bytes_scanned: int
    total_bytes_stored: int
    total_duration_sec: float
    
    # Block stats (for identifying outliers)
    slowest_block_id: Optional[str] = None
    slowest_block_duration: float = 0.0
    fastest_block_id: Optional[str] = None
    fastest_block_duration: float = float('inf')
    
    @property
    def avg_throughput_files_sec(self) -> float:
        """Average files per second across all blocks."""
        if self.total_duration_sec <= 0:
            return 0.0
        return self.total_files_scanned / self.total_duration_sec
    
    @property
    def avg_throughput_mb_sec(self) -> float:
        """Average MB per second across all blocks."""
        if self.total_duration_sec <= 0:
            return 0.0
        return (self.total_bytes_scanned / (1024 * 1024)) / self.total_duration_sec
    
    @property
    def error_rate(self) -> float:
        """Fraction of files that had errors."""
        if self.total_files_scanned <= 0:
            return 0.0
        return self.total_files_skipped_error / self.total_files_scanned
    
    @property
    def compression_ratio(self) -> float:
        """Ratio of bytes stored to bytes scanned (parser efficiency)."""
        if self.total_bytes_scanned <= 0:
            return 0.0
        return self.total_bytes_stored / self.total_bytes_scanned
    
    def format_summary(self) -> str:
        """Format a multi-line summary for status display."""
        mb_scanned = self.total_bytes_scanned / (1024 * 1024)
        mb_stored = self.total_bytes_stored / (1024 * 1024)
        
        lines = [
            f"=== {self.phase} Summary ===",
            f"  Blocks: {self.total_blocks}",
            f"  Files:  {self.total_files_scanned} scanned, {self.total_files_processed} processed",
            f"  Skipped: {self.total_files_skipped_uptodate} uptodate, {self.total_files_skipped_error} errors, {self.total_files_skipped_ignored} ignored",
            f"  Data:   {mb_scanned:.1f}MB scanned → {mb_stored:.1f}MB stored ({self.compression_ratio:.1%} ratio)",
            f"  Time:   {self.total_duration_sec:.1f}s ({self.avg_throughput_files_sec:.1f} files/s, {self.avg_throughput_mb_sec:.1f} MB/s)",
        ]
        
        if self.total_files_skipped_error > 0:
            lines.append(f"  Errors: {self.error_rate:.1%} error rate")
        
        if self.slowest_block_id:
            lines.append(f"  Slowest: block {self.slowest_block_id} ({self.slowest_block_duration:.1f}s)")
        
        return "\n".join(lines)


@dataclass
class _BlockState:
    """Internal mutable state for the current block being built."""
    
    started_at: datetime
    files_scanned: int = 0
    files_processed: int = 0
    files_skipped_uptodate: int = 0
    files_skipped_error: int = 0
    files_skipped_ignored: int = 0
    bytes_scanned: int = 0
    bytes_stored: int = 0
    file_hashes: List[str] = field(default_factory=list)
    errors: List[Dict] = field(default_factory=list)


class BlockTracker:
    """Manages block lifecycle during daemon execution.
    
    Usage:
        tracker = BlockTracker(conn, build_id, "ingest")
        
        for file in files:
            size = file.stat().st_size
            try:
                process(file)
                tracker.record_file(str(file), size, "processed", content_hash=hash)
            except Exception as e:
                tracker.record_file(str(file), size, "error", error_info={"type": str(type(e)), "msg": str(e)})
        
        tracker.flush()  # Close final partial block
    
    The tracker automatically closes blocks when thresholds are met.
    """
    
    def __init__(
        self,
        conn: sqlite3.Connection,
        build_id: str,
        phase: str,
        file_threshold: int = FILE_THRESHOLD,
        byte_threshold: int = BYTE_THRESHOLD,
        logger=None,
    ):
        self.conn = conn
        self.build_id = build_id
        self.phase = phase
        self.file_threshold = file_threshold
        self.byte_threshold = byte_threshold
        self.logger = logger
        
        self._block_number = 0
        self._current: Optional[_BlockState] = None
        self._completed_blocks: List[BlockLog] = []
        
        # Start first block
        self._open_block()
    
    def _open_block(self) -> None:
        """Open a new block."""
        self._block_number += 1
        self._current = _BlockState(started_at=datetime.now())
        if self.logger:
            self.logger.debug(f"Opened block #{self._block_number} for {self.phase}")
    
    def record_file(
        self,
        path: str,
        size_bytes: int,
        status: FileStatus,
        content_hash: Optional[str] = None,
        bytes_stored: int = 0,
        error_info: Optional[Dict] = None,
    ) -> Optional[BlockLog]:
        """Record a file operation.
        
        Args:
            path: File path (for error manifest and hash)
            size_bytes: File size in bytes
            status: One of "processed", "uptodate", "error", "ignored"
            content_hash: SHA256 of file content (for Merkle tree)
            bytes_stored: Bytes written to DB for this file
            error_info: Error details if status == "error"
        
        Returns:
            BlockLog if this record caused a block to close, else None.
        """
        if self._current is None:
            self._open_block()
        
        state = self._current
        
        # Update metrics
        state.files_scanned += 1
        state.bytes_scanned += size_bytes
        state.bytes_stored += bytes_stored
        
        if status == "processed":
            state.files_processed += 1
        elif status == "uptodate":
            state.files_skipped_uptodate += 1
        elif status == "error":
            state.files_skipped_error += 1
            if error_info:
                state.errors.append({
                    "path": path,
                    "type": error_info.get("type", "Unknown"),
                    "message": error_info.get("msg", "")[:500],  # Truncate long messages
                })
        elif status == "ignored":
            state.files_skipped_ignored += 1
        
        # Track hash for Merkle root
        if content_hash:
            state.file_hashes.append(content_hash)
        else:
            # Generate hash from path if no content hash provided
            state.file_hashes.append(hashlib.sha256(path.encode()).hexdigest()[:16])
        
        # Check thresholds
        if state.files_scanned >= self.file_threshold or state.bytes_scanned >= self.byte_threshold:
            return self.close_block()
        
        return None
    
    def close_block(self) -> BlockLog:
        """Close current block, persist to DB, and open new block.
        
        Returns:
            The completed BlockLog record.
        """
        if self._current is None:
            raise RuntimeError("No block is open")
        
        state = self._current
        ended_at = datetime.now()
        duration = (ended_at - state.started_at).total_seconds()
        
        # Compute Merkle root
        block_hash = self._compute_merkle_root(state.file_hashes)
        
        # Create immutable record
        block = BlockLog(
            block_id=f"blk-{uuid.uuid4().hex[:8]}",
            build_id=self.build_id,
            phase=self.phase,
            block_number=self._block_number,
            started_at=state.started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_sec=duration,
            files_scanned=state.files_scanned,
            files_processed=state.files_processed,
            files_skipped_uptodate=state.files_skipped_uptodate,
            files_skipped_error=state.files_skipped_error,
            files_skipped_ignored=state.files_skipped_ignored,
            bytes_scanned=state.bytes_scanned,
            bytes_stored=state.bytes_stored,
            block_hash=block_hash,
            error_manifest=json.dumps(state.errors) if state.errors else None,
        )
        
        # Persist to database
        self._persist_block(block)
        
        # Track completed block
        self._completed_blocks.append(block)
        
        if self.logger:
            self.logger.info(block.format_summary())
        
        # Reset for next block
        self._current = None
        self._open_block()
        
        return block
    
    def flush(self) -> Optional[BlockLog]:
        """Close any partial block. Call at end of phase.
        
        Returns:
            BlockLog if there was a partial block, else None.
        """
        if self._current is None or self._current.files_scanned == 0:
            return None
        
        return self.close_block()
    
    def get_current_stats(self) -> Dict:
        """Get stats for in-progress block (for status display)."""
        if self._current is None:
            return {}
        
        state = self._current
        elapsed = (datetime.now() - state.started_at).total_seconds()
        
        return {
            "block_number": self._block_number,
            "files_scanned": state.files_scanned,
            "files_processed": state.files_processed,
            "bytes_scanned": state.bytes_scanned,
            "elapsed_sec": elapsed,
            "files_remaining": self.file_threshold - state.files_scanned,
            "bytes_remaining": self.byte_threshold - state.bytes_scanned,
        }
    
    def get_stage_summary(self) -> StageSummary:
        """Get aggregated summary for this phase."""
        blocks = self._completed_blocks
        
        summary = StageSummary(
            phase=self.phase,
            build_id=self.build_id,
            total_blocks=len(blocks),
            total_files_scanned=sum(b.files_scanned for b in blocks),
            total_files_processed=sum(b.files_processed for b in blocks),
            total_files_skipped_uptodate=sum(b.files_skipped_uptodate for b in blocks),
            total_files_skipped_error=sum(b.files_skipped_error for b in blocks),
            total_files_skipped_ignored=sum(b.files_skipped_ignored for b in blocks),
            total_bytes_scanned=sum(b.bytes_scanned for b in blocks),
            total_bytes_stored=sum(b.bytes_stored for b in blocks),
            total_duration_sec=sum(b.duration_sec for b in blocks),
        )
        
        # Find slowest/fastest blocks
        if blocks:
            slowest = max(blocks, key=lambda b: b.duration_sec)
            fastest = min(blocks, key=lambda b: b.duration_sec)
            summary.slowest_block_id = slowest.block_id
            summary.slowest_block_duration = slowest.duration_sec
            summary.fastest_block_id = fastest.block_id
            summary.fastest_block_duration = fastest.duration_sec
        
        return summary
    
    def _compute_merkle_root(self, hashes: List[str]) -> str:
        """Compute Merkle root of file hashes.
        
        This creates a tree of hashes that can be used to verify
        the integrity of the block and identify which files changed.
        """
        if not hashes:
            return hashlib.sha256(b"empty").hexdigest()[:16]
        
        # Pad to power of 2
        n = len(hashes)
        next_pow2 = 1
        while next_pow2 < n:
            next_pow2 *= 2
        
        # Duplicate last hash to pad
        padded = hashes + [hashes[-1]] * (next_pow2 - n)
        
        # Build tree bottom-up
        while len(padded) > 1:
            next_level = []
            for i in range(0, len(padded), 2):
                combined = padded[i] + padded[i + 1]
                next_level.append(hashlib.sha256(combined.encode()).hexdigest()[:16])
            padded = next_level
        
        return padded[0]
    
    def _persist_block(self, block: BlockLog) -> None:
        """Write block to system_ingest_log table."""
        self.conn.execute("""
            INSERT INTO system_ingest_log (
                block_id, build_id, phase, block_number,
                started_at, ended_at, duration_sec,
                files_scanned, files_processed, 
                files_skipped_uptodate, files_skipped_error, files_skipped_ignored,
                bytes_scanned, bytes_stored,
                block_hash, error_manifest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            block.block_id, block.build_id, block.phase, block.block_number,
            block.started_at, block.ended_at, block.duration_sec,
            block.files_scanned, block.files_processed,
            block.files_skipped_uptodate, block.files_skipped_error, block.files_skipped_ignored,
            block.bytes_scanned, block.bytes_stored,
            block.block_hash, block.error_manifest,
        ))
        self.conn.commit()


# === Query Functions ===

def get_recent_blocks(
    conn: sqlite3.Connection,
    limit: int = 5,
    build_id: Optional[str] = None,
    phase: Optional[str] = None,
) -> List[BlockLog]:
    """Get most recent blocks from database.
    
    Args:
        conn: Database connection
        limit: Max blocks to return
        build_id: Filter to specific build (optional)
        phase: Filter to specific phase (optional)
    
    Returns:
        List of BlockLog records, most recent first.
    """
    conn.row_factory = sqlite3.Row
    
    query = "SELECT * FROM system_ingest_log WHERE 1=1"
    params = []
    
    if build_id:
        query += " AND build_id = ?"
        params.append(build_id)
    
    if phase:
        query += " AND phase = ?"
        params.append(phase)
    
    query += " ORDER BY ended_at DESC LIMIT ?"
    params.append(limit)
    
    cursor = conn.execute(query, params)
    return [BlockLog.from_row(row) for row in cursor.fetchall()]


def get_stage_summary_from_db(
    conn: sqlite3.Connection,
    build_id: str,
    phase: str,
) -> Optional[StageSummary]:
    """Get aggregated summary for a phase from database.
    
    Args:
        conn: Database connection
        build_id: Build UUID
        phase: Phase name
    
    Returns:
        StageSummary or None if no blocks found.
    """
    conn.row_factory = sqlite3.Row
    
    cursor = conn.execute("""
        SELECT 
            COUNT(*) as total_blocks,
            SUM(files_scanned) as total_files_scanned,
            SUM(files_processed) as total_files_processed,
            SUM(files_skipped_uptodate) as total_files_skipped_uptodate,
            SUM(files_skipped_error) as total_files_skipped_error,
            SUM(files_skipped_ignored) as total_files_skipped_ignored,
            SUM(bytes_scanned) as total_bytes_scanned,
            SUM(bytes_stored) as total_bytes_stored,
            SUM(duration_sec) as total_duration_sec
        FROM system_ingest_log
        WHERE build_id = ? AND phase = ?
    """, (build_id, phase))
    
    row = cursor.fetchone()
    if not row or row["total_blocks"] == 0:
        return None
    
    summary = StageSummary(
        phase=phase,
        build_id=build_id,
        total_blocks=row["total_blocks"],
        total_files_scanned=row["total_files_scanned"] or 0,
        total_files_processed=row["total_files_processed"] or 0,
        total_files_skipped_uptodate=row["total_files_skipped_uptodate"] or 0,
        total_files_skipped_error=row["total_files_skipped_error"] or 0,
        total_files_skipped_ignored=row["total_files_skipped_ignored"] or 0,
        total_bytes_scanned=row["total_bytes_scanned"] or 0,
        total_bytes_stored=row["total_bytes_stored"] or 0,
        total_duration_sec=row["total_duration_sec"] or 0.0,
    )
    
    # Find slowest/fastest blocks
    slowest = conn.execute("""
        SELECT block_id, duration_sec FROM system_ingest_log
        WHERE build_id = ? AND phase = ?
        ORDER BY duration_sec DESC LIMIT 1
    """, (build_id, phase)).fetchone()
    
    fastest = conn.execute("""
        SELECT block_id, duration_sec FROM system_ingest_log
        WHERE build_id = ? AND phase = ?
        ORDER BY duration_sec ASC LIMIT 1
    """, (build_id, phase)).fetchone()
    
    if slowest:
        summary.slowest_block_id = slowest["block_id"]
        summary.slowest_block_duration = slowest["duration_sec"]
    
    if fastest:
        summary.fastest_block_id = fastest["block_id"]
        summary.fastest_block_duration = fastest["duration_sec"]
    
    return summary


def format_blocks_for_status(blocks: List[BlockLog], verbose: bool = False) -> str:
    """Format blocks for CLI status display.
    
    Args:
        blocks: List of BlockLog records
        verbose: Include error manifests if True
    
    Returns:
        Formatted string for display.
    """
    if not blocks:
        return "  (no blocks recorded yet)"
    
    lines = []
    for block in blocks:
        lines.append("  " + block.format_summary())
        
        if verbose and block.error_manifest:
            errors = json.loads(block.error_manifest)
            for err in errors[:5]:  # Limit to 5 errors per block
                lines.append(f"    - {err['path']}: {err['type']} - {err['message'][:80]}")
            if len(errors) > 5:
                lines.append(f"    ... and {len(errors) - 5} more errors")
    
    return "\n".join(lines)


def get_all_blocks_jsonl(
    conn: sqlite3.Connection,
    build_id: Optional[str] = None,
) -> str:
    """Get all blocks as JSON Lines format.
    
    Args:
        conn: Database connection
        build_id: Filter to specific build (optional)
    
    Returns:
        JSONL string (one JSON object per line).
    """
    blocks = get_recent_blocks(conn, limit=10000, build_id=build_id)
    lines = [json.dumps(block.to_dict()) for block in blocks]
    return "\n".join(lines)


def cleanup_old_builds(
    conn: sqlite3.Connection,
    keep_builds: int = 10,
) -> int:
    """Remove block logs from old builds.
    
    Args:
        conn: Database connection
        keep_builds: Number of recent builds to keep
    
    Returns:
        Number of blocks deleted.
    """
    # Get builds to keep
    cursor = conn.execute("""
        SELECT DISTINCT build_id FROM system_ingest_log
        ORDER BY MAX(ended_at) DESC
        LIMIT ?
    """, (keep_builds,))
    
    builds_to_keep = [row[0] for row in cursor.fetchall()]
    
    if not builds_to_keep:
        return 0
    
    # Delete old builds
    placeholders = ",".join("?" * len(builds_to_keep))
    result = conn.execute(f"""
        DELETE FROM system_ingest_log
        WHERE build_id NOT IN ({placeholders})
    """, builds_to_keep)
    
    deleted = result.rowcount
    conn.commit()
    
    return deleted
