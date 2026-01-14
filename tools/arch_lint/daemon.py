"""
arch_lint v2.35 — File watch daemon.

Continuously lints recently edited files first.
Writes findings to timestamped JSON log files.
Requires: pip install watchdog

Usage:
    python -m tools.arch_lint --daemon
    python -m tools.arch_lint --daemon --interval 1.0 --full-scan-mins 30
    
Log files are written to: ~/.ck3raven/logs/arch_lint/
"""

from __future__ import annotations

import json
import sys
import time
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Conditional import for watchdog - optional dependency
try:
    from watchdog.observers import Observer  # type: ignore[import-not-found]
    from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
    _WATCHDOG_AVAILABLE = True
except ImportError:
    Observer = None  # type: ignore[misc,assignment]
    FileSystemEventHandler = None  # type: ignore[misc,assignment]
    _WATCHDOG_AVAILABLE = False

from .config import LintConfig
from .scanner import load_source
from .analysis import build_index
from .reporting import Finding
from .rules import (
    check_direct_terms,
    check_composites,
    check_comments,
    check_path_apis,
    check_enforcement_sites,
    check_io_and_mutators,
    check_oracle_patterns,
    check_fallback_patterns,
    check_concept_explosion,
)


def _get_log_dir() -> Path:
    """Get the log directory, creating if needed."""
    log_dir = Path.home() / ".ck3raven" / "logs" / "arch_lint"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _get_log_path() -> Path:
    """Get timestamped log file path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _get_log_dir() / f"arch_lint_{ts}.json"


class _RecentQueue:
    """Thread-safe priority queue for recently modified files."""
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: Dict[str, float] = {}  # path -> last_ts
    
    def push(self, path: Path, ts: float) -> None:
        p = str(path)
        with self._lock:
            prev = self._items.get(p)
            if prev is None or ts > prev:
                self._items[p] = ts
    
    def pop_most_recent(self) -> Optional[Tuple[Path, float]]:
        with self._lock:
            if not self._items:
                return None
            p, ts = max(self._items.items(), key=lambda kv: kv[1])
            del self._items[p]
            return Path(p), ts
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class _PyChangeHandler:
    """Watches for Python file changes."""
    
    SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".wip", "archive"}
    
    def __init__(self, root: Path, queue: _RecentQueue) -> None:
        self.root = root
        self.queue = queue
    
    def on_modified(self, event: Any) -> None:
        if getattr(event, 'is_directory', False):
            return
        p = Path(event.src_path)
        if p.suffix != ".py":
            return
        if any(part in self.SKIP_DIRS for part in p.parts):
            return
        self.queue.push(p, time.time())
    
    def on_created(self, event: Any) -> None:
        self.on_modified(event)


def _lint_one_file(cfg: LintConfig, path: Path) -> Tuple[List[Finding], List[Finding]]:
    """Lint a single file and return (errors, warnings)."""
    try:
        src = load_source(path)
    except Exception as e:
        f = Finding(
            rule_id="READ_FAIL",
            severity="WARN",
            path=str(path),
            line=1,
            col=1,
            message=f"Could not read file: {e}",
        )
        return [], [f]
    
    idx = build_index(src)
    findings: List[Finding] = []
    
    findings.extend(check_direct_terms(cfg, src))
    findings.extend(check_composites(cfg, src))
    findings.extend(check_comments(cfg, src))
    findings.extend(check_path_apis(cfg, src))
    findings.extend(check_enforcement_sites(cfg, src))
    findings.extend(check_io_and_mutators(cfg, src, idx))
    findings.extend(check_oracle_patterns(cfg, src, idx))
    findings.extend(check_fallback_patterns(cfg, src))
    findings.extend(check_concept_explosion(cfg, src, idx))
    
    errors = [f for f in findings if f.severity == "ERROR"]
    warns = [f for f in findings if f.severity in ("WARN", "DOC-WARN")]
    return errors, warns


class _JsonLogger:
    """Appends findings to a JSON log file."""
    
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._lock = threading.Lock()
        self._entries: List[Dict[str, Any]] = []
        # Write initial header
        self._write_header()
    
    def _write_header(self) -> None:
        """Write log file header."""
        header = {
            "type": "session_start",
            "timestamp": datetime.now().isoformat(),
            "version": "2.35",
        }
        with self._lock:
            self._entries.append(header)
            self._flush()
    
    def log_findings(self, path: str, errors: List[Finding], warns: List[Finding]) -> None:
        """Log findings for a file."""
        entry = {
            "type": "lint_result",
            "timestamp": datetime.now().isoformat(),
            "file": path,
            "error_count": len(errors),
            "warning_count": len(warns),
            "findings": [asdict(f) for f in errors + warns],
        }
        with self._lock:
            self._entries.append(entry)
            self._flush()
    
    def log_full_scan(self, error_count: int, warning_count: int) -> None:
        """Log a full scan completion."""
        entry = {
            "type": "full_scan",
            "timestamp": datetime.now().isoformat(),
            "error_count": error_count,
            "warning_count": warning_count,
        }
        with self._lock:
            self._entries.append(entry)
            self._flush()
    
    def _flush(self) -> None:
        """Write all entries to disk."""
        self.log_path.write_text(json.dumps(self._entries, indent=2, default=str))


def _print_findings(errors: List[Finding], warns: List[Finding], max_warns: int = 50) -> None:
    """Print findings to stdout."""
    if not errors and not warns:
        return
    
    for f in errors:
        print(f"ERROR {f.rule_id} {f.path}:{f.line}:{f.col} — {f.message}")
        if f.evidence:
            print(f"    {f.evidence}")
    
    for f in warns[:max_warns]:
        print(f"WARN  {f.rule_id} {f.path}:{f.line}:{f.col} — {f.message}")
        if f.evidence:
            print(f"    {f.evidence}")
    
    if len(warns) > max_warns:
        print(f"... {len(warns) - max_warns} more warnings suppressed")


def _full_scan(root: Path, logger: Optional[_JsonLogger] = None) -> int:
    """Run a full scan."""
    from .runner import run
    cfg = LintConfig(root=root)
    reporter = run(root, cfg)
    print(reporter.render_human())
    
    if logger:
        logger.log_full_scan(len(reporter.errors), len(reporter.warnings))
    
    return 1 if reporter.errors else 0


def run_daemon(
    root: Path,
    interval: float,
    debounce_seconds: float,
    full_scan_mins: int,
) -> int:
    """Run the daemon loop."""
    if not _WATCHDOG_AVAILABLE or Observer is None:
        print("Daemon mode requires watchdog: pip install watchdog")
        return 1
    
    # Set up JSON logging
    log_path = _get_log_path()
    logger = _JsonLogger(log_path)
    
    cfg = LintConfig(root=root)
    queue = _RecentQueue()
    handler = _PyChangeHandler(root, queue)
    
    # Create observer and wrap handler for watchdog compatibility
    observer = Observer()
    
    # Wrap handler methods for watchdog
    class _WatchdogAdapter:
        def __init__(self, h: _PyChangeHandler):
            self._h = h
        def dispatch(self, event: Any) -> None:
            if hasattr(event, 'event_type'):
                if event.event_type in ('modified', 'created'):
                    self._h.on_modified(event)
    
    adapter = _WatchdogAdapter(handler)
    observer.schedule(adapter, str(root), recursive=True)  # type: ignore
    observer.start()
    
    print(f"[arch_lint_daemon] watching {root}")
    print(f"[arch_lint_daemon] interval={interval}s debounce={debounce_seconds}s full_scan={full_scan_mins}m")
    print(f"[arch_lint_daemon] logging to: {log_path}")
    
    last_linted: Dict[str, float] = {}
    last_full_scan = time.time()
    
    try:
        while True:
            now = time.time()
            
            # Periodic full scan
            if full_scan_mins > 0 and (now - last_full_scan) >= (full_scan_mins * 60):
                print(f"\n[arch_lint_daemon] full scan starting...")
                rc = _full_scan(root, logger)
                print(f"[arch_lint_daemon] full scan finished rc={rc}\n")
                last_full_scan = now
            
            item = queue.pop_most_recent()
            if item is None:
                time.sleep(interval)
                continue
            
            path, ts = item
            p = str(path)
            
            # Debounce
            prev = last_linted.get(p, 0.0)
            if (now - prev) < debounce_seconds:
                continue
            last_linted[p] = now
            
            # Lint this file
            errors, warns = _lint_one_file(cfg, path)
            if errors or warns:
                print(f"\n[arch_lint_daemon] lint {path} (queue={len(queue)})")
                _print_findings(errors, warns)
                logger.log_findings(p, errors, warns)
            
            time.sleep(interval)
    
    except KeyboardInterrupt:
        print("\n[arch_lint_daemon] stopping...")
        print(f"[arch_lint_daemon] log written to: {log_path}")
    finally:
        observer.stop()
        observer.join()
    
    return 0
