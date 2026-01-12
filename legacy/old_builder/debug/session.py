"""
DebugSession - Unified debug infrastructure for the daemon pipeline.

Design principles:
1. OBSERVE the pipeline, don't re-implement it
2. Phase-agnostic: phases call debug.emit/span, session handles output
3. Data-driven: collect timings, row deltas, sizes
4. Non-invasive: no phase-specific logic in the debug layer

Usage:
    debug = DebugSession.from_config(output_dir, config)
    
    # In any phase:
    with debug.span("file", phase="parse", path=path) as s:
        ast = parse(content)
        s.add(ast_bytes=len(blob), nodes=count)
    
    debug.emit("db_write", table="symbols", rows=100)
    
    # At end:
    debug.close()  # Writes summary
"""
from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, Literal


# Standard event types (add new types here, not in phases)
EventType = Literal[
    # Lifecycle
    "session_start", "session_end",
    "phase_start", "phase_end",
    
    # File-level 
    "file_start", "file_end",
    
    # Parse results
    "parse_ok", "parse_fail",
    
    # Database operations
    "db_write", "db_read",
    
    # Extraction artifacts
    "artifact",
    
    # Warnings and diagnostics
    "warning", "error",
    
    # Aggregates
    "summary",
]


@dataclass
class DebugConfig:
    """Configuration for debug session."""
    enabled: bool = True
    
    # Sampling
    sample_mode: Literal["all", "first_n", "random", "threshold"] = "first_n"
    sample_limit: int = 100
    sample_threshold_ms: float = 100.0  # Only record if slower than this
    
    # Filtering
    phase_filter: list[str] | None = None  # None = all phases
    path_pattern: str | None = None  # Glob pattern for paths
    
    # Output
    output_trace: bool = True  # Write JSONL trace
    output_summary: bool = True  # Write summary JSON
    
    # Detail level
    include_content_samples: bool = False  # Include content snippets
    max_content_sample_bytes: int = 500


@dataclass
class SpanContext:
    """Context for a timing span."""
    session: DebugSession
    event_type: str
    start_time: float
    data: dict[str, Any] = field(default_factory=dict)
    _closed: bool = False
    
    def add(self, **kwargs: Any) -> None:
        """Add data to this span."""
        self.data.update(kwargs)
    
    def close(self) -> None:
        """Close the span and emit the event."""
        if self._closed:
            return
        self._closed = True
        
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        self.data["ms"] = round(elapsed_ms, 2)
        self.session.emit(self.event_type, **self.data)


@dataclass 
class PhaseStats:
    """Accumulated stats for a phase."""
    name: str
    started_at: float = 0.0
    ended_at: float = 0.0
    files_processed: int = 0
    total_ms: float = 0.0
    total_input_bytes: int = 0
    total_output_count: int = 0
    errors: int = 0
    warnings: int = 0
    
    # Bloat tracking
    worst_by_time: list[dict] = field(default_factory=list)
    worst_by_size: list[dict] = field(default_factory=list)
    worst_by_bloat: list[dict] = field(default_factory=list)


class DebugSession:
    """
    Unified debug session that phases hook into.
    
    All debug output goes through this class. Phases should not
    implement their own debug logic.
    """
    
    def __init__(self, output_dir: Path, config: DebugConfig | None = None):
        self.output_dir = output_dir
        self.config = config or DebugConfig()
        
        self.run_id = hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]
        self.started_at = time.time()
        
        self._trace_file = None
        self._event_count = 0
        self._sample_count: dict[str, int] = {}  # phase -> count
        
        # Per-phase stats
        self._phases: dict[str, PhaseStats] = {}
        self._current_phase: str | None = None
        
        # Ensure output dir exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Open trace file
        if self.config.output_trace:
            trace_path = self.output_dir / "debug_trace.jsonl"
            self._trace_file = trace_path.open("w", encoding="utf-8")
        
        # Emit session start
        self.emit("session_start", run_id=self.run_id, config=self._config_to_dict())
    
    @classmethod
    def from_config(
        cls, 
        output_dir: Path | str,
        enabled: bool = True,
        sample_limit: int = 100,
        phase_filter: list[str] | None = None,
    ) -> DebugSession:
        """Create a debug session from simple parameters."""
        config = DebugConfig(
            enabled=enabled,
            sample_limit=sample_limit,
            phase_filter=phase_filter,
        )
        return cls(Path(output_dir), config)
    
    @classmethod
    def disabled(cls) -> DebugSession:
        """Create a disabled debug session (no-op)."""
        import tempfile
        config = DebugConfig(enabled=False, output_trace=False, output_summary=False)
        return cls(Path(tempfile.gettempdir()), config)
    
    def _config_to_dict(self) -> dict:
        """Convert config to dict for serialization."""
        return {
            "enabled": self.config.enabled,
            "sample_mode": self.config.sample_mode,
            "sample_limit": self.config.sample_limit,
            "phase_filter": self.config.phase_filter,
        }
    
    def _should_sample(self, phase: str) -> bool:
        """Check if we should sample this event."""
        if not self.config.enabled:
            return False
        
        if self.config.phase_filter and phase not in self.config.phase_filter:
            return False
        
        if self.config.sample_mode == "all":
            return True
        
        if self.config.sample_mode == "first_n":
            count = self._sample_count.get(phase, 0)
            return count < self.config.sample_limit
        
        # Add other modes as needed
        return True
    
    def emit(self, event_type: str, **data: Any) -> None:
        """
        Emit a debug event.
        
        This is the primary interface for phases to record debug data.
        """
        if not self.config.enabled:
            return
        
        phase = data.get("phase", self._current_phase or "unknown")
        
        # Track sample count
        if event_type in ("file_start", "file_end"):
            if not self._should_sample(phase):
                return
            if event_type == "file_end":
                self._sample_count[phase] = self._sample_count.get(phase, 0) + 1
        
        event = {
            "t": event_type,
            "ts": time.time(),
            "phase": phase,
            **data,
        }
        
        # Write to trace file
        if self._trace_file:
            self._trace_file.write(json.dumps(event) + "\n")
            self._trace_file.flush()
        
        self._event_count += 1
        
        # Update phase stats
        if event_type == "file_end" and phase in self._phases:
            stats = self._phases[phase]
            stats.files_processed += 1
            stats.total_ms += data.get("ms", 0)
            stats.total_input_bytes += data.get("input_bytes", 0)
            stats.total_output_count += data.get("output_count", 0)
            
            # Track worst performers
            self._update_worst(stats, data)
        
        if event_type == "error":
            if phase in self._phases:
                self._phases[phase].errors += 1
        
        if event_type == "warning":
            if phase in self._phases:
                self._phases[phase].warnings += 1
    
    def _update_worst(self, stats: PhaseStats, data: dict) -> None:
        """Update worst-case tracking lists."""
        record = {
            "path": data.get("path", "unknown"),
            "ms": data.get("ms", 0),
            "input_bytes": data.get("input_bytes", 0),
            "output_count": data.get("output_count", 0),
        }
        
        # Calculate bloat ratio
        if record["input_bytes"] > 0:
            output_bytes = data.get("output_bytes", 0)
            record["bloat_ratio"] = round(output_bytes / record["input_bytes"], 2)
        else:
            record["bloat_ratio"] = 0
        
        # Keep top 50 by each metric
        limit = 50
        
        stats.worst_by_time.append(record)
        stats.worst_by_time.sort(key=lambda x: x["ms"], reverse=True)
        stats.worst_by_time = stats.worst_by_time[:limit]
        
        stats.worst_by_size.append(record)
        stats.worst_by_size.sort(key=lambda x: x["input_bytes"], reverse=True)
        stats.worst_by_size = stats.worst_by_size[:limit]
        
        stats.worst_by_bloat.append(record)
        stats.worst_by_bloat.sort(key=lambda x: x["bloat_ratio"], reverse=True)
        stats.worst_by_bloat = stats.worst_by_bloat[:limit]
    
    @contextmanager
    def span(
        self, 
        event_type: str = "file",
        **initial_data: Any
    ) -> Generator[SpanContext, None, None]:
        """
        Context manager for timing a span.
        
        Usage:
            with debug.span("file", phase="parse", path=path) as s:
                result = do_work()
                s.add(output_count=len(result))
        """
        ctx = SpanContext(
            session=self,
            event_type=f"{event_type}_end",
            start_time=time.perf_counter(),
            data=dict(initial_data),
        )
        
        # Emit start event
        self.emit(f"{event_type}_start", **initial_data)
        
        try:
            yield ctx
        finally:
            ctx.close()
    
    def phase_start(self, phase: str) -> None:
        """Mark the start of a phase."""
        self._current_phase = phase
        
        if phase not in self._phases:
            self._phases[phase] = PhaseStats(name=phase)
        
        self._phases[phase].started_at = time.time()
        self.emit("phase_start", phase=phase)
    
    def phase_end(self, phase: str) -> None:
        """Mark the end of a phase."""
        if phase in self._phases:
            self._phases[phase].ended_at = time.time()
        
        self.emit("phase_end", phase=phase)
        self._current_phase = None
    
    def close(self) -> None:
        """Close the session and write summary."""
        # Emit session end
        self.emit("session_end", 
            event_count=self._event_count,
            duration_sec=round(time.time() - self.started_at, 2)
        )
        
        # Close trace file
        if self._trace_file:
            self._trace_file.close()
            self._trace_file = None
        
        # Write summary
        if self.config.output_summary:
            self._write_summary()
    
    def _write_summary(self) -> None:
        """Write summary JSON file."""
        summary = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "duration_sec": round(time.time() - self.started_at, 2),
            "event_count": self._event_count,
            "phases": {},
        }
        
        for name, stats in self._phases.items():
            phase_duration = stats.ended_at - stats.started_at if stats.ended_at else 0
            avg_ms = stats.total_ms / stats.files_processed if stats.files_processed else 0
            rate = stats.files_processed / phase_duration if phase_duration > 0 else 0
            
            summary["phases"][name] = {
                "files_processed": stats.files_processed,
                "total_ms": round(stats.total_ms, 2),
                "avg_ms": round(avg_ms, 2),
                "rate_per_sec": round(rate, 1),
                "errors": stats.errors,
                "warnings": stats.warnings,
                "worst_by_time": stats.worst_by_time[:20],
                "worst_by_size": stats.worst_by_size[:20],
                "worst_by_bloat": stats.worst_by_bloat[:20],
            }
        
        summary_path = self.output_dir / "debug_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    
    def __enter__(self) -> DebugSession:
        return self
    
    def __exit__(self, *args) -> None:
        self.close()
