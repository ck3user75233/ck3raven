"""
QBuilder JSONL Logging - Structured logging for build operations.

Writes timestamped JSON entries to ~/.ck3raven/logs/qbuilder_YYYY-MM-DD.jsonl

Log entry types:
- run_start: Build run started
- run_complete: Build run finished
- step_start: Executor step started
- step_complete: Executor step finished
- step_error: Executor step failed
- item_claimed: Work item claimed
- item_complete: Work item finished
- item_error: Work item failed
"""

from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, asdict


def get_log_dir() -> Path:
    """Get the logs directory, creating if needed."""
    log_dir = Path.home() / ".ck3raven" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file() -> Path:
    """Get today's log file path."""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_log_dir() / f"qbuilder_{today}.jsonl"


@dataclass
class LogEntry:
    """A structured log entry."""
    ts: float  # Unix timestamp
    event: str  # Event type
    run_id: Optional[str] = None
    worker_id: Optional[str] = None
    file_id: Optional[int] = None
    relpath: Optional[str] = None
    step: Optional[str] = None
    envelope: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    stats: Optional[dict] = None
    extra: Optional[dict] = None
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        d = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(d, default=str)


class QBuilderLogger:
    """
    Structured logger for QBuilder operations.
    
    Writes to JSONL file for easy parsing and analysis.
    """
    
    def __init__(
        self,
        run_id: str,
        worker_id: Optional[str] = None,
        log_file: Optional[Path] = None,
    ):
        self.run_id = run_id
        self.worker_id = worker_id
        self.log_file = log_file or get_log_file()
        
        # Step timing
        self._step_starts: dict[str, float] = {}
        self._item_starts: dict[int, float] = {}
    
    def _write(self, entry: LogEntry) -> None:
        """Write an entry to the log file."""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")
    
    def _entry(self, event: str, **kwargs) -> LogEntry:
        """Create a log entry with common fields."""
        return LogEntry(
            ts=time.time(),
            event=event,
            run_id=self.run_id,
            worker_id=self.worker_id,
            **kwargs,
        )
    
    # =========================================================================
    # Run-level events
    # =========================================================================
    
    def log_event(self, event: str, data: Optional[dict] = None) -> None:
        """Log a generic event with optional data."""
        self._write(self._entry(event, extra=data))
    
    def run_start(self, playset: Optional[str] = None, total_items: int = 0) -> None:
        """Log the start of a build run."""
        self._write(self._entry(
            "run_start",
            stats={"playset": playset, "total_items": total_items},
        ))
    
    def run_complete(
        self,
        processed: int = 0,
        errors: int = 0,
        duration_ms: float = 0,
    ) -> None:
        """Log the completion of a build run."""
        self._write(self._entry(
            "run_complete",
            duration_ms=duration_ms,
            stats={"processed": processed, "errors": errors},
        ))
    
    # =========================================================================
    # Item-level events
    # =========================================================================
    
    def item_claimed(
        self,
        file_id: int,
        relpath: str,
        envelope: str,
        steps: tuple[str, ...],
    ) -> None:
        """Log when a work item is claimed."""
        self._item_starts[file_id] = time.time()
        self._write(self._entry(
            "item_claimed",
            file_id=file_id,
            relpath=relpath,
            envelope=envelope,
            extra={"steps": list(steps)},
        ))
    
    def item_complete(self, file_id: int, relpath: str) -> None:
        """Log when a work item completes."""
        start = self._item_starts.pop(file_id, None)
        duration_ms = (time.time() - start) * 1000 if start else None
        
        self._write(self._entry(
            "item_complete",
            file_id=file_id,
            relpath=relpath,
            duration_ms=duration_ms,
        ))
    
    def item_error(
        self,
        file_id: int,
        relpath: str,
        error: str,
        step: Optional[str] = None,
    ) -> None:
        """Log when a work item fails."""
        start = self._item_starts.pop(file_id, None)
        duration_ms = (time.time() - start) * 1000 if start else None
        
        self._write(self._entry(
            "item_error",
            file_id=file_id,
            relpath=relpath,
            step=step,
            error=error[:500],  # Truncate long errors
            duration_ms=duration_ms,
        ))
    
    # =========================================================================
    # Step-level events
    # =========================================================================
    
    def step_start(self, file_id: int, step: str) -> None:
        """Log when an executor step starts."""
        key = f"{file_id}:{step}"
        self._step_starts[key] = time.time()
        
        self._write(self._entry(
            "step_start",
            file_id=file_id,
            step=step,
        ))
    
    def step_complete(
        self,
        file_id: int,
        step: str,
        stats: Optional[dict] = None,
    ) -> None:
        """Log when an executor step completes."""
        key = f"{file_id}:{step}"
        start = self._step_starts.pop(key, None)
        duration_ms = (time.time() - start) * 1000 if start else None
        
        self._write(self._entry(
            "step_complete",
            file_id=file_id,
            step=step,
            duration_ms=duration_ms,
            stats=stats,
        ))
    
    def step_error(
        self,
        file_id: int,
        step: str,
        error: str,
    ) -> None:
        """Log when an executor step fails."""
        key = f"{file_id}:{step}"
        start = self._step_starts.pop(key, None)
        duration_ms = (time.time() - start) * 1000 if start else None
        
        self._write(self._entry(
            "step_error",
            file_id=file_id,
            step=step,
            error=error[:500],
            duration_ms=duration_ms,
        ))


# =============================================================================
# Log Analysis Utilities
# =============================================================================

def read_log_entries(
    log_file: Optional[Path] = None,
    event_filter: Optional[str] = None,
    run_id: Optional[str] = None,
) -> list[dict]:
    """
    Read and parse log entries from a JSONL file.
    
    Args:
        log_file: Path to log file (default: today's log)
        event_filter: Only return entries with this event type
        run_id: Only return entries from this run
    
    Returns:
        List of parsed log entry dicts
    """
    log_file = log_file or get_log_file()
    
    if not log_file.exists():
        return []
    
    entries = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                entry = json.loads(line)
                
                if event_filter and entry.get("event") != event_filter:
                    continue
                
                if run_id and entry.get("run_id") != run_id:
                    continue
                
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    
    return entries


def summarize_run(run_id: str, log_file: Optional[Path] = None) -> dict:
    """
    Summarize a build run from log entries.
    
    Returns:
        Summary dict with timing and error stats
    """
    entries = read_log_entries(log_file, run_id=run_id)
    
    if not entries:
        return {"error": "No entries found for run"}
    
    summary = {
        "run_id": run_id,
        "total_entries": len(entries),
        "items_claimed": 0,
        "items_complete": 0,
        "items_error": 0,
        "step_counts": {},
        "step_durations_ms": {},
        "errors": [],
    }
    
    for entry in entries:
        event = entry.get("event")
        
        if event == "item_claimed":
            summary["items_claimed"] += 1
        elif event == "item_complete":
            summary["items_complete"] += 1
        elif event == "item_error":
            summary["items_error"] += 1
            summary["errors"].append({
                "file_id": entry.get("file_id"),
                "relpath": entry.get("relpath"),
                "step": entry.get("step"),
                "error": entry.get("error"),
            })
        elif event == "step_complete":
            step = entry.get("step", "unknown")
            summary["step_counts"][step] = summary["step_counts"].get(step, 0) + 1
            
            duration = entry.get("duration_ms")
            if duration:
                if step not in summary["step_durations_ms"]:
                    summary["step_durations_ms"][step] = []
                summary["step_durations_ms"][step].append(duration)
    
    # Calculate averages
    for step, durations in summary["step_durations_ms"].items():
        if durations:
            summary["step_durations_ms"][step] = {
                "count": len(durations),
                "avg_ms": sum(durations) / len(durations),
                "min_ms": min(durations),
                "max_ms": max(durations),
                "total_ms": sum(durations),
            }
    
    return summary
