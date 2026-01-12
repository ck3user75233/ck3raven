"""
Worker with atomic leasing for queue-based build daemon.

Provides crash-safe work claiming with automatic lease expiration.
If a worker crashes, its leased work will be reclaimed after timeout.

Usage:
    from builder.worker import WorkerSession
    
    with WorkerSession(conn, worker_id="worker-1", lease_seconds=300) as worker:
        while True:
            work = worker.claim_work()
            if work is None:
                break
            try:
                process(work)
                worker.complete_work(work.work_id)
            except Exception as e:
                worker.error_work(work.work_id, str(e))
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional
import sqlite3
import uuid

from builder.routing import ProcessingStage, get_processing_envelope


@dataclass
class WorkItem:
    """A claimed work item from the queue."""
    work_id: int
    file_id: int
    content_version_id: int
    processing_mask: int
    file_type: str
    priority: int
    queued_at: str
    retry_count: int
    
    @property
    def stages(self) -> ProcessingStage:
        """Get processing stages as IntFlag."""
        return ProcessingStage(self.processing_mask)


class WorkerSession:
    """
    A worker session with atomic leasing.
    
    Use as a context manager to ensure proper cleanup.
    """
    
    def __init__(
        self,
        conn: sqlite3.Connection,
        worker_id: str | None = None,
        lease_seconds: int = 300,
    ):
        """
        Initialize worker session.
        
        Args:
            conn: Database connection
            worker_id: Unique worker identifier (auto-generated if None)
            lease_seconds: How long to hold lease before timeout
        """
        self.conn = conn
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self._active_work: list[int] = []  # work_ids we've claimed
    
    def __enter__(self) -> "WorkerSession":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Release any work we still have claimed
        if self._active_work:
            self._release_all()
        return False  # Don't suppress exceptions
    
    def _release_all(self) -> None:
        """Release all work this worker has claimed."""
        if not self._active_work:
            return
        
        placeholders = ",".join("?" * len(self._active_work))
        self.conn.execute(f"""
            UPDATE work_queue 
            SET status = 'pending',
                worker_id = NULL,
                lease_expires_at = NULL
            WHERE work_id IN ({placeholders})
              AND status = 'processing'
        """, self._active_work)
        self.conn.commit()
        self._active_work.clear()
    
    def claim_work(self, batch_size: int = 1) -> Optional[WorkItem]:
        """
        Atomically claim the next available work item.
        
        Uses UPDATE ... RETURNING for atomic claim with lease.
        Falls back to SELECT + UPDATE for older SQLite versions.
        
        Args:
            batch_size: Number of items to claim (currently only 1 supported)
            
        Returns:
            WorkItem if work was claimed, None if queue is empty
        """
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=self.lease_seconds)
        now_iso = now.isoformat()
        lease_iso = lease_expires.isoformat()
        
        # First, reclaim any expired leases
        self._reclaim_expired_leases(now_iso)
        
        # Try to claim work using UPDATE ... RETURNING (SQLite 3.35+)
        try:
            row = self.conn.execute("""
                UPDATE work_queue
                SET status = 'processing',
                    worker_id = ?,
                    started_at = ?,
                    lease_expires_at = ?
                WHERE work_id = (
                    SELECT work_id FROM work_queue
                    WHERE status = 'pending'
                    ORDER BY priority ASC, queued_at ASC
                    LIMIT 1
                )
                RETURNING work_id, file_id, content_version_id, processing_mask,
                          file_type, priority, queued_at, retry_count
            """, (self.worker_id, now_iso, lease_iso)).fetchone()
        except sqlite3.OperationalError:
            # RETURNING not supported, fall back to SELECT + UPDATE
            row = self._claim_work_fallback(now_iso, lease_iso)
        
        if row is None:
            return None
        
        work = WorkItem(
            work_id=row[0],
            file_id=row[1],
            content_version_id=row[2],
            processing_mask=row[3],
            file_type=row[4],
            priority=row[5],
            queued_at=row[6],
            retry_count=row[7],
        )
        
        self._active_work.append(work.work_id)
        self.conn.commit()
        return work
    
    def _claim_work_fallback(self, now_iso: str, lease_iso: str) -> Optional[tuple]:
        """Fallback claim for SQLite < 3.35."""
        # Use a transaction to ensure atomicity
        row = self.conn.execute("""
            SELECT work_id, file_id, content_version_id, processing_mask,
                   file_type, priority, queued_at, retry_count
            FROM work_queue
            WHERE status = 'pending'
            ORDER BY priority ASC, queued_at ASC
            LIMIT 1
        """).fetchone()
        
        if row is None:
            return None
        
        work_id = row[0]
        affected = self.conn.execute("""
            UPDATE work_queue
            SET status = 'processing',
                worker_id = ?,
                started_at = ?,
                lease_expires_at = ?
            WHERE work_id = ? AND status = 'pending'
        """, (self.worker_id, now_iso, lease_iso, work_id)).rowcount
        
        if affected == 0:
            # Another worker grabbed it, try again
            return self._claim_work_fallback(now_iso, lease_iso)
        
        return row
    
    def _reclaim_expired_leases(self, now_iso: str) -> int:
        """Reclaim work from crashed workers."""
        affected = self.conn.execute("""
            UPDATE work_queue
            SET status = 'pending',
                worker_id = NULL,
                started_at = NULL,
                lease_expires_at = NULL,
                retry_count = retry_count + 1
            WHERE status = 'processing'
              AND lease_expires_at < ?
        """, (now_iso,)).rowcount
        
        if affected > 0:
            self.conn.commit()
        
        return affected
    
    def complete_work(self, work_id: int, rows_affected: int = 0) -> None:
        """
        Mark work as completed successfully.
        
        Args:
            work_id: The work item to complete
            rows_affected: Optional count for logging
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        
        self.conn.execute("""
            UPDATE work_queue
            SET status = 'completed',
                completed_at = ?,
                worker_id = NULL,
                lease_expires_at = NULL
            WHERE work_id = ?
        """, (now_iso, work_id))
        
        # Log completion
        self.conn.execute("""
            INSERT INTO processing_log (
                work_id, file_id, event_type, logged_at, rows_affected, worker_id
            )
            SELECT ?, file_id, 'completed', ?, ?, ?
            FROM work_queue WHERE work_id = ?
        """, (work_id, now_iso, rows_affected, self.worker_id, work_id))
        
        self.conn.commit()
        
        if work_id in self._active_work:
            self._active_work.remove(work_id)
    
    def error_work(
        self,
        work_id: int,
        error_message: str,
        error_code: str = "PROCESSING_ERROR",
        *,
        max_retries: int = 3,
    ) -> None:
        """
        Mark work as failed.
        
        If retry_count < max_retries, will be retried.
        Otherwise marked as permanently failed.
        
        Args:
            work_id: The work item that failed
            error_message: Error description
            error_code: Error category code
            max_retries: Max retries before permanent failure
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Get current retry count
        row = self.conn.execute(
            "SELECT retry_count FROM work_queue WHERE work_id = ?",
            (work_id,)
        ).fetchone()
        
        if row is None:
            return  # Work doesn't exist
        
        retry_count = row[0]
        
        if retry_count < max_retries:
            # Put back for retry
            new_status = 'pending'
            new_retry = retry_count + 1
        else:
            # Permanent failure
            new_status = 'failed'
            new_retry = retry_count
        
        self.conn.execute("""
            UPDATE work_queue
            SET status = ?,
                error_message = ?,
                error_code = ?,
                retry_count = ?,
                worker_id = NULL,
                lease_expires_at = NULL
            WHERE work_id = ?
        """, (new_status, error_message, error_code, new_retry, work_id))
        
        # Log error
        self.conn.execute("""
            INSERT INTO processing_log (
                work_id, file_id, event_type, logged_at, error_message, worker_id
            )
            SELECT ?, file_id, 'error', ?, ?, ?
            FROM work_queue WHERE work_id = ?
        """, (work_id, now_iso, error_message, self.worker_id, work_id))
        
        self.conn.commit()
        
        if work_id in self._active_work:
            self._active_work.remove(work_id)
    
    def renew_lease(self, work_id: int) -> bool:
        """
        Extend the lease on active work.
        
        Call this for long-running processing to prevent timeout.
        
        Args:
            work_id: The work item to renew
            
        Returns:
            True if renewed, False if work is no longer ours
        """
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=self.lease_seconds)
        lease_iso = lease_expires.isoformat()
        
        affected = self.conn.execute("""
            UPDATE work_queue
            SET lease_expires_at = ?
            WHERE work_id = ?
              AND worker_id = ?
              AND status = 'processing'
        """, (lease_iso, work_id, self.worker_id)).rowcount
        
        self.conn.commit()
        return affected > 0


def queue_pending_work(
    conn: sqlite3.Connection,
    pending,  # PendingWork from change_detector
    *,
    priority: int = 100,
) -> Optional[int]:
    """
    Queue a PendingWork item for processing.
    
    Args:
        conn: Database connection
        pending: PendingWork object from change_detector
        priority: Work priority (lower = higher priority)
        
    Returns:
        work_id if queued, None if already queued with same mask
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # Get file type from routing
    envelope = get_processing_envelope(pending.relpath)
    
    # Insert or update work queue entry
    conn.execute("""
        INSERT INTO work_queue (
            file_id, content_version_id, processing_mask, file_type,
            status, priority, queued_at
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            processing_mask = processing_mask | excluded.processing_mask,
            status = CASE 
                WHEN work_queue.status IN ('completed', 'failed') THEN 'pending'
                ELSE work_queue.status
            END,
            priority = MIN(work_queue.priority, excluded.priority),
            queued_at = CASE 
                WHEN work_queue.status = 'pending' THEN work_queue.queued_at
                ELSE excluded.queued_at
            END,
            error_message = NULL,
            error_code = NULL
    """, (
        pending.file_id,
        pending.content_version_id,
        pending.processing_mask,
        envelope.file_type,
        priority,
        now_iso,
    ))
    
    conn.commit()
    
    # Get the work_id
    row = conn.execute(
        "SELECT work_id FROM work_queue WHERE file_id = ?",
        (pending.file_id,)
    ).fetchone()
    
    return row[0] if row else None


def queue_work(
    conn: sqlite3.Connection,
    change,  # DetectedChange - kept for compatibility
    *,
    priority: int = 100,
) -> Optional[int]:
    """
    Queue a detected change for processing.
    
    Gets the processing envelope and creates a work_queue entry.
    Handles DELETED changes by removing from queue.
    
    Args:
        conn: Database connection
        change: The detected change
        priority: Work priority (lower = higher priority)
        
    Returns:
        work_id if queued, None if deleted or already queued
    """
    from builder.change_detector import ChangeType
    
    now_iso = datetime.now(timezone.utc).isoformat()
    
    if hasattr(change, 'change_type') and change.change_type == ChangeType.DELETED:
        # Remove any existing work for this file
        conn.execute(
            "DELETE FROM work_queue WHERE file_id = ?",
            (change.file_id,)
        )
        conn.commit()
        return None
    
    # Get processing envelope
    envelope = get_processing_envelope(change.relpath)
    
    # Insert or update work queue entry
    # If file already queued, update its processing mask
    conn.execute("""
        INSERT INTO work_queue (
            file_id, content_version_id, processing_mask, file_type,
            status, priority, queued_at
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            processing_mask = excluded.processing_mask,
            status = 'pending',
            priority = MIN(work_queue.priority, excluded.priority),
            queued_at = CASE 
                WHEN work_queue.status = 'pending' THEN work_queue.queued_at
                ELSE excluded.queued_at
            END,
            error_message = NULL,
            error_code = NULL
    """, (
        change.file_id,
        change.content_version_id,
        envelope.stages.value,
        envelope.file_type,
        priority,
        now_iso,
    ))
    
    conn.commit()
    
    # Get the work_id
    row = conn.execute(
        "SELECT work_id FROM work_queue WHERE file_id = ?",
        (change.file_id,)
    ).fetchone()
    
    return row[0] if row else None


def get_queue_stats(conn: sqlite3.Connection) -> dict:
    """
    Get queue statistics.
    
    Returns:
        Dict with counts by status
    """
    rows = conn.execute("""
        SELECT status, COUNT(*) as count
        FROM work_queue
        GROUP BY status
    """).fetchall()
    
    stats = {
        'pending': 0,
        'processing': 0,
        'completed': 0,
        'failed': 0,
    }
    
    for status, count in rows:
        stats[status] = count
    
    stats['total'] = sum(stats.values())
    
    return stats


# --- Self-test ---
if __name__ == "__main__":
    print("Worker module loaded successfully")
    print(f"WorkItem fields: {list(WorkItem.__dataclass_fields__.keys())}")
    print(f"WorkerSession methods: claim_work, complete_work, error_work, renew_lease")
    print(f"Queue functions: queue_work, queue_pending_work, get_queue_stats")
