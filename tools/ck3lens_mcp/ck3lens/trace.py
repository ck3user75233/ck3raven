from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Iterator


class ToolTrace:
    """
    Tool trace logger and reader for policy validation.
    
    Logs MCP tool calls to a JSONL file for later analysis by the policy validator.
    """
    
    def __init__(self, trace_path: Path) -> None:
        self.trace_path = trace_path
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, tool: str, args: dict[str, Any], result_summary: dict[str, Any]) -> None:
        """
        Log a tool call event.
        
        Args:
            tool: Tool name (e.g., "ck3lens.search_symbols")
            args: Tool arguments
            result_summary: Summary of the result (not full result to save space)
        """
        event = {
            "ts": time.time(),
            "tool": tool,
            "args": args,
            "result": result_summary,
        }
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    
    def read_all(self) -> list[dict[str, Any]]:
        """
        Read all trace events from the log file.
        
        Returns:
            List of trace event dicts, oldest first.
        """
        if not self.trace_path.exists():
            return []
        
        events = []
        with self.trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events
    
    def read_recent(self, max_events: int = 100, since_ts: float | None = None) -> list[dict[str, Any]]:
        """
        Read recent trace events.
        
        Args:
            max_events: Maximum number of events to return
            since_ts: Only return events after this timestamp
        
        Returns:
            List of trace event dicts, newest first.
        """
        all_events = self.read_all()
        
        if since_ts is not None:
            all_events = [e for e in all_events if e.get("ts", 0) > since_ts]
        
        # Return most recent, newest first
        return list(reversed(all_events[-max_events:]))
    
    def iter_events(self) -> Iterator[dict[str, Any]]:
        """
        Iterate over trace events without loading all into memory.
        
        Yields:
            Trace event dicts, oldest first.
        """
        if not self.trace_path.exists():
            return
        
        with self.trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    
    def clear(self) -> None:
        """Clear the trace log file."""
        if self.trace_path.exists():
            self.trace_path.write_text("")
    
    def get_session_trace(self, session_start_ts: float) -> list[dict[str, Any]]:
        """
        Get all events from the current session.
        
        Args:
            session_start_ts: Timestamp when the session started
        
        Returns:
            List of trace events from this session.
        """
        return [e for e in self.read_all() if e.get("ts", 0) >= session_start_ts]
    
    @property
    def event_count(self) -> int:
        """Count total events in trace file."""
        if not self.trace_path.exists():
            return 0
        
        count = 0
        with self.trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
