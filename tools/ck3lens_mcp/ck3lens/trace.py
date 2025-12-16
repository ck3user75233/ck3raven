from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

class ToolTrace:
    def __init__(self, trace_path: Path) -> None:
        self.trace_path = trace_path
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, tool: str, args: dict[str, Any], result_summary: dict[str, Any]) -> None:
        event = {
            "ts": time.time(),
            "tool": tool,
            "args": args,
            "result": result_summary,
        }
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
