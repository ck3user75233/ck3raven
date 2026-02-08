"""
Persistent Parse Pool — Supervisor for long-lived parse worker processes.

This module manages a pool of parse_worker subprocesses that:
- Import parser/serde ONCE at startup (amortizes ~115ms spawn + ~22ms import)
- Process many files via JSON line protocol
- Get killed on timeout, respawned automatically
- Recycle after N parses to bound memory leaks

Usage:
    from ck3raven.parser.parse_pool import ParsePool
    
    pool = ParsePool(num_workers=4)
    pool.start()
    
    result = pool.parse_file(Path("/path/to/file.txt"), timeout=30)
    if result.success:
        ast_json = result.ast_json
    
    pool.shutdown()

Integration with qbuilder:
    Enable via QBUILDER_PERSISTENT_PARSE=1 environment variable.
    The pool is created once when qbuilder daemon starts.
"""

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from typing import Dict, List, Optional
import signal


# Default configuration
DEFAULT_NUM_WORKERS = min(os.cpu_count() or 2, 4)
DEFAULT_TIMEOUT_MS = 30000
WORKER_STARTUP_TIMEOUT = 10.0  # seconds to wait for worker ready signal
WORKER_RECYCLE_AFTER = 5000  # respawn worker after this many parses


@dataclass
class ParseResult:
    """Result from pool parse operation."""
    success: bool
    ast_json: Optional[str] = None
    node_count: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None


class WorkerProcess:
    """
    Wrapper around a single parse worker subprocess.
    
    Handles:
    - Spawning the worker
    - Sending requests via stdin
    - Reading responses via stdout
    - Killing on timeout
    - Detecting crashes and recycling
    """
    
    def __init__(self, worker_id: int, repo_root: Path):
        self.worker_id = worker_id
        self.repo_root = repo_root
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.parse_count = 0
        self.lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._response_queue: Queue = Queue()
        self._pending_requests: Dict[str, threading.Event] = {}
        self._pending_responses: Dict[str, dict] = {}
    
    def start(self) -> bool:
        """
        Start the worker subprocess.
        
        Returns True if worker started and sent ready signal.
        """
        python_exe = sys.executable
        worker_module = str(self.repo_root / "src" / "ck3raven" / "parser" / "parse_worker.py")
        
        env = {
            **os.environ,
            "CK3RAVEN_ROOT": str(self.repo_root),
            "PYTHONPATH": str(self.repo_root / "src"),
        }
        
        try:
            self.process = subprocess.Popen(
                [python_exe, worker_module],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=str(self.repo_root),
                bufsize=1,  # Line buffered
            )
        except Exception as e:
            print(f"[Pool] Failed to spawn worker {self.worker_id}: {e}")
            return False
        
        # Wait for ready signal
        try:
            ready_line = self.process.stdout.readline()
            if not ready_line:
                print(f"[Pool] Worker {self.worker_id} closed stdout immediately")
                self.kill()
                return False
            
            ready_msg = json.loads(ready_line.strip())
            if ready_msg.get("ready"):
                self.pid = ready_msg.get("pid", self.process.pid)
                self.parse_count = 0
                
                # Start reader thread
                self._reader_thread = threading.Thread(
                    target=self._read_responses,
                    daemon=True,
                    name=f"ParseWorker-{self.worker_id}-reader"
                )
                self._reader_thread.start()
                
                return True
            else:
                print(f"[Pool] Worker {self.worker_id} sent unexpected ready: {ready_msg}")
                self.kill()
                return False
                
        except Exception as e:
            print(f"[Pool] Worker {self.worker_id} failed during startup: {e}")
            self.kill()
            return False
    
    def _read_responses(self):
        """Background thread that reads responses from worker stdout."""
        while self.process and self.process.poll() is None:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                
                response = json.loads(line.strip())
                
                # Check for recycle signal
                if response.get("recycle"):
                    # Worker wants to recycle - will exit after this
                    continue
                
                req_id = response.get("id")
                if req_id and req_id in self._pending_requests:
                    self._pending_responses[req_id] = response
                    self._pending_requests[req_id].set()
                    
            except json.JSONDecodeError:
                continue
            except Exception:
                break
    
    def is_alive(self) -> bool:
        """Check if worker process is still running."""
        return self.process is not None and self.process.poll() is None
    
    def needs_recycle(self) -> bool:
        """Check if worker should be recycled due to parse count."""
        return self.parse_count >= WORKER_RECYCLE_AFTER
    
    def parse_file(self, filepath: Path, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> ParseResult:
        """
        Send a parse request to this worker.
        
        Args:
            filepath: Absolute path to file
            timeout_ms: Timeout in milliseconds
            
        Returns:
            ParseResult with AST or error
        """
        if not self.is_alive():
            return ParseResult(
                success=False,
                error_type="WorkerDead",
                error="Worker process is not alive",
            )
        
        req_id = str(uuid.uuid4())
        request = {
            "id": req_id,
            "path": str(filepath),
            "timeout_ms": timeout_ms,
        }
        
        # Set up response event
        response_event = threading.Event()
        self._pending_requests[req_id] = response_event
        
        try:
            with self.lock:
                self.process.stdin.write(json.dumps(request) + "\n")
                self.process.stdin.flush()
            
            # Wait for response with timeout
            timeout_sec = (timeout_ms / 1000) + 2.0  # Add buffer for IPC overhead
            got_response = response_event.wait(timeout=timeout_sec)
            
            if not got_response:
                # Timeout - kill worker (supervisor will respawn)
                self.kill()
                return ParseResult(
                    success=False,
                    error_type="ParseTimeoutError",
                    error=f"Parse timeout after {timeout_ms}ms: {filepath}",
                )
            
            response = self._pending_responses.pop(req_id, None)
            if not response:
                return ParseResult(
                    success=False,
                    error_type="NoResponse",
                    error="Response event fired but no response data",
                )
            
            self.parse_count += 1
            
            if response.get("ok"):
                return ParseResult(
                    success=True,
                    ast_json=response.get("ast_json"),
                    node_count=response.get("node_count", 0),
                )
            else:
                return ParseResult(
                    success=False,
                    error_type=response.get("error_type", "ParseError"),
                    error=response.get("error", "Unknown error"),
                )
                
        except BrokenPipeError:
            return ParseResult(
                success=False,
                error_type="WorkerCrashed",
                error="Worker process crashed (broken pipe)",
            )
        except Exception as e:
            return ParseResult(
                success=False,
                error_type=type(e).__name__,
                error=str(e),
            )
        finally:
            self._pending_requests.pop(req_id, None)
    
    def kill(self):
        """Kill the worker process."""
        if self.process:
            try:
                self.process.kill()
                self.process.wait(timeout=2.0)
            except Exception:
                pass
            self.process = None
            self.pid = None
    
    def shutdown(self):
        """Gracefully shutdown the worker."""
        if self.process and self.is_alive():
            try:
                # Send shutdown command
                self.process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
                self.process.stdin.flush()
                self.process.wait(timeout=2.0)
            except Exception:
                self.kill()
        self.process = None


class ParsePool:
    """
    Pool of persistent parse workers.
    
    Manages worker lifecycle:
    - Spawns workers on start()
    - Routes parse requests to available workers
    - Respawns crashed/timed-out workers
    - Recycles workers after N parses
    - Shuts down cleanly on shutdown()
    """
    
    def __init__(self, num_workers: int = DEFAULT_NUM_WORKERS):
        self.num_workers = num_workers
        self.repo_root = self._get_repo_root()
        self.workers: List[WorkerProcess] = []
        self._worker_lock = threading.Lock()
        self._next_worker = 0
        self._running = False
    
    def _get_repo_root(self) -> Path:
        """Get ck3raven repo root."""
        # This file is at src/ck3raven/parser/parse_pool.py
        return Path(__file__).parent.parent.parent.parent
    
    def start(self):
        """Start all workers in the pool."""
        if self._running:
            return
        
        self._running = True
        
        for i in range(self.num_workers):
            worker = WorkerProcess(i, self.repo_root)
            if worker.start():
                self.workers.append(worker)
                print(f"[Pool] Started worker {i} (pid={worker.pid})")
            else:
                print(f"[Pool] Failed to start worker {i}")
        
        if not self.workers:
            raise RuntimeError("Failed to start any parse workers")
        
        print(f"[Pool] Started {len(self.workers)}/{self.num_workers} workers")
    
    def _get_worker(self) -> Optional[WorkerProcess]:
        """Get next available worker (round-robin)."""
        with self._worker_lock:
            if not self.workers:
                return None
            
            # Round-robin selection
            worker = self.workers[self._next_worker % len(self.workers)]
            self._next_worker += 1
            
            # Check if worker needs respawn
            if not worker.is_alive() or worker.needs_recycle():
                worker_id = worker.worker_id
                worker.kill()
                
                # Respawn
                new_worker = WorkerProcess(worker_id, self.repo_root)
                if new_worker.start():
                    idx = self.workers.index(worker)
                    self.workers[idx] = new_worker
                    print(f"[Pool] Respawned worker {worker_id} (pid={new_worker.pid})")
                    return new_worker
                else:
                    print(f"[Pool] Failed to respawn worker {worker_id}")
                    return None
            
            return worker
    
    def parse_file(self, filepath: Path, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> ParseResult:
        """
        Parse a file using the worker pool.
        
        Args:
            filepath: Absolute path to file
            timeout_ms: Timeout in milliseconds
            
        Returns:
            ParseResult with AST or error
        """
        if not self._running:
            return ParseResult(
                success=False,
                error_type="PoolNotRunning",
                error="Parse pool is not running",
            )
        
        worker = self._get_worker()
        if not worker:
            return ParseResult(
                success=False,
                error_type="NoWorkerAvailable",
                error="No parse worker available",
            )
        
        result = worker.parse_file(filepath, timeout_ms)
        
        # If worker crashed/timed out, it was killed - next call will respawn
        return result
    
    def parse_text(self, content: str, filename: str = "<inline>", 
                   timeout_ms: int = DEFAULT_TIMEOUT_MS) -> ParseResult:
        """
        Parse text content using the worker pool.
        
        Args:
            content: Text content to parse
            filename: Filename for error messages
            timeout_ms: Timeout in milliseconds
            
        Returns:
            ParseResult with AST or error
        """
        if not self._running:
            return ParseResult(
                success=False,
                error_type="PoolNotRunning", 
                error="Parse pool is not running",
            )
        
        worker = self._get_worker()
        if not worker:
            return ParseResult(
                success=False,
                error_type="NoWorkerAvailable",
                error="No parse worker available",
            )
        
        # For text parsing, we need to extend the worker protocol
        # For now, fall back to subprocess (TODO: add content mode to worker)
        # This is fine because text parsing is rare (MCP tools only)
        from ck3raven.parser.runtime import parse_text as runtime_parse_text
        runtime_result = runtime_parse_text(content, filename, timeout_ms // 1000)
        
        return ParseResult(
            success=runtime_result.success,
            ast_json=runtime_result.ast_json,
            node_count=runtime_result.node_count,
            error=runtime_result.error,
            error_type=runtime_result.error_type,
        )
    
    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "num_workers": len(self.workers),
            "target_workers": self.num_workers,
            "running": self._running,
            "workers": [
                {
                    "id": w.worker_id,
                    "pid": w.pid,
                    "alive": w.is_alive(),
                    "parse_count": w.parse_count,
                }
                for w in self.workers
            ],
        }
    
    def shutdown(self):
        """Shutdown all workers."""
        self._running = False
        
        for worker in self.workers:
            worker.shutdown()
        
        self.workers.clear()
        print("[Pool] Shutdown complete")


# Global pool instance (initialized lazily)
_global_pool: Optional[ParsePool] = None
_pool_lock = threading.Lock()


def get_pool() -> ParsePool:
    """
    Get or create the global parse pool.
    
    The pool is created lazily on first access.
    """
    global _global_pool
    
    with _pool_lock:
        if _global_pool is None:
            _global_pool = ParsePool()
            _global_pool.start()
        return _global_pool


def shutdown_pool():
    """Shutdown the global parse pool."""
    global _global_pool
    
    with _pool_lock:
        if _global_pool is not None:
            _global_pool.shutdown()
            _global_pool = None


def is_pool_enabled() -> bool:
    """Check if persistent parse pool is enabled (default: True).
    
    Set QBUILDER_PERSISTENT_PARSE=0 to disable and fall back to subprocess-per-file.
    """
    return os.environ.get("QBUILDER_PERSISTENT_PARSE", "1").lower() not in ("0", "false", "no")
