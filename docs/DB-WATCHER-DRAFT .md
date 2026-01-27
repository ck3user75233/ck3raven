Audit & Implementation Plan: DB Self-Update Mechanism
I have audited the qbuilder codebase (specifically daemon.py, cli.py, discovery.py, and api.py) from the provided export.

1. Code Audit: What We Have vs. What is Missing
Current State: The architecture is set up as a "Pull" system (polling the queue) rather than a "Push" system (reacting to events).

✅ Persistence & Queueing (schema.py, api.py):

You have a robust build_queue that acts as the buffer for work.

enqueue_file() (in api.py) correctly handles "Flash" priority (priority=1), which ensures user edits jump to the front of the line.

The database schema supports content_hash deduplication, meaning if a file is saved but bytes haven't changed, the logic can detect it (though currently enqueue_file forces an update to files table).

✅ Single-Writer Daemon (cli.py):

cmd_daemon sets up the WriterLock and the DaemonIPCServer thread.

It runs run_build_worker in the main thread, which continuously polls the DB for work.

❌ The Missing Link (The Watcher):

There is zero code importing watchdog or similar libraries.

The cmd_daemon function knows how to work, but it doesn't know when files change unless enqueue_file is called manually (via IPC).

Currently, you rely on the user or VS Code extension manually triggering a file refresh.

2. Recommended Implementation: The "Observer Thread"
The best way to add this is to introduce a third component to the Daemon process. Currently, you have:

Main Thread: Build Worker (Polls DB -> Processes Files)

Thread 2: IPC Server (Listens to TCP -> Enqueues to DB)

We will add: 3. Thread 3: File System Watcher (Listens to OS Events -> Enqueues to DB)

This keeps the architecture clean: The Watcher doesn't process files; it simply "pokes" the database via enqueue_file, utilizing the existing queue/priority system.

Concrete Implementation Guide
Step 1: Add Dependency
Add watchdog to your pyproject.toml dependencies.

Step 2: Create qbuilder/watcher.py
This new module will handle the OS-level event listening. It needs to be robust against "event storms" (e.g., git operations or "Save All").

Python
"""
QBuilder Watcher - Filesystem observer for the daemon.
"""
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from qbuilder.api import enqueue_file, PRIORITY_FLASH

logger = logging.getLogger(__name__)

class ChangeHandler(FileSystemEventHandler):
    """Maps OS events to QBuilder DB operations."""
    
    def __init__(self, mod_map):
        self.mod_map = mod_map  # Dict mapping {absolute_path: mod_name}

    def on_modified(self, event):
        if event.is_directory: return
        self._process_event(event.src_path)

    def on_created(self, event):
        if event.is_directory: return
        self._process_event(event.src_path)

    def _process_event(self, file_path):
        path = Path(file_path)
        # Filter out noise
        if path.suffix not in {'.txt', '.yml', '.gui', '.gfx'}: return
        
        # Resolve which mod this belongs to
        for root, mod_name in self.mod_map.items():
            if path.is_relative_to(root):
                rel_path = path.relative_to(root)
                # PUSH to DB - High Priority
                enqueue_file(
                    mod_name=mod_name, 
                    rel_path=str(rel_path), 
                    priority=PRIORITY_FLASH
                )
                logger.info(f"Detected change: {mod_name}/{rel_path}")
                break

class WatcherService:
    """Manages the watchdog observer thread."""
    
    def __init__(self, conn):
        self.conn = conn
        self.observer = Observer()
        self.active = False

    def start(self):
        # 1. Query DB for active mod roots to watch
        # We only watch what is currently indexed
        rows = self.conn.execute("""
            SELECT mp.name, mp.source_path 
            FROM mod_packages mp 
            JOIN content_versions cv ON mp.mod_package_id = cv.mod_package_id
            WHERE mp.source_path IS NOT NULL
        """).fetchall()

        mod_map = {Path(r['source_path']): r['name'] for r in rows}
        handler = ChangeHandler(mod_map)

        # 2. Schedule watches
        for path in mod_map.keys():
            if path.exists():
                self.observer.schedule(handler, str(path), recursive=True)
                logger.info(f"Watching: {path}")

        self.observer.start()
        self.active = True

    def stop(self):
        if self.active:
            self.observer.stop()
            self.observer.join()
            self.active = False
Step 3: Wire into qbuilder/cli.py
Update cmd_daemon to start the watcher alongside the IPC server.

Python
# qbuilder/cli.py

def cmd_daemon(args: argparse.Namespace) -> int:
    # ... existing setup ...
    from .watcher import WatcherService  # Import the new service
    
    try:
        # ... IPC Server start ...
        
        # --- NEW CODE START ---
        print("Starting filesystem watcher...")
        # Use a fresh connection for the watcher thread if needed, 
        # or pass the main one if it's strictly read-only setup
        watcher = WatcherService(get_connection()) 
        watcher.start()
        # --- NEW CODE END ---

        # ... Existing Worker Loop ...
        result = run_build_worker(...)

        # ... Shutdown sequence ...
        watcher.stop()  # Stop watcher on exit
        ipc_server.stop()
        
    finally:
        lock.release()
Step 4: Handle "Deletions" (The Missing Logic)
The agent noted that deletion detection was missing. watchdog has an on_deleted event. You need to map this to api.delete_file (which exists but wasn't wired).

Update ChangeHandler in watcher.py:

Python
    def on_deleted(self, event):
        if event.is_directory: return
        path = Path(event.src_path)
        
        for root, mod_name in self.mod_map.items():
            if path.is_relative_to(root):
                rel_path = path.relative_to(root)
                # Call the existing API
                from qbuilder.api import delete_file
                delete_file(mod_name, str(rel_path))
                logger.info(f"Detected deletion: {mod_name}/{rel_path}")
                break
This effectively closes the loop. The Daemon now has eyes (Watcher), a brain (DB/Queue), and hands (Worker).




1. Code Audit: What We Have vs. What is Missing
Current State: The architecture is set up as a "Pull" system (polling the queue) rather than a "Push" system (reacting to events).

✅ Persistence & Queueing (schema.py, api.py):

You have a robust build_queue that acts as the buffer for work.

enqueue_file() (in api.py) correctly handles "Flash" priority (priority=1), which ensures user edits jump to the front of the line.

The database schema supports content_hash deduplication, meaning if a file is saved but bytes haven't changed, the logic can detect it (though currently enqueue_file forces an update to files table).

✅ Single-Writer Daemon (cli.py):

cmd_daemon sets up the WriterLock and the DaemonIPCServer thread.

It runs run_build_worker in the main thread, which continuously polls the DB for work.

❌ The Missing Link (The Watcher):

There is zero code importing watchdog or similar libraries.

The cmd_daemon function knows how to work, but it doesn't know when files change unless enqueue_file is called manually (via IPC).

Currently, you rely on the user or VS Code extension manually triggering a file refresh.

2. Recommended Implementation: The "Observer Thread"
The best way to add this is to introduce a third component to the Daemon process. Currently, you have:

Main Thread: Build Worker (Polls DB -> Processes Files)

Thread 2: IPC Server (Listens to TCP -> Enqueues to DB)

We will add: 3. Thread 3: File System Watcher (Listens to OS Events -> Enqueues to DB)

This keeps the architecture clean: The Watcher doesn't process files; it simply "pokes" the database via enqueue_file, utilizing the existing queue/priority system.

Concrete Implementation Guide
Step 1: Add Dependency
Add watchdog to your pyproject.toml dependencies.

Step 2: Create qbuilder/watcher.py
This new module will handle the OS-level event listening. It needs to be robust against "event storms" (e.g., git operations or "Save All").

Python
"""
QBuilder Watcher - Filesystem observer for the daemon.
"""
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from qbuilder.api import enqueue_file, PRIORITY_FLASH

logger = logging.getLogger(__name__)

class ChangeHandler(FileSystemEventHandler):
    """Maps OS events to QBuilder DB operations."""
    
    def __init__(self, mod_map):
        self.mod_map = mod_map  # Dict mapping {absolute_path: mod_name}

    def on_modified(self, event):
        if event.is_directory: return
        self._process_event(event.src_path)

    def on_created(self, event):
        if event.is_directory: return
        self._process_event(event.src_path)

    def _process_event(self, file_path):
        path = Path(file_path)
        # Filter out noise
        if path.suffix not in {'.txt', '.yml', '.gui', '.gfx'}: return
        
        # Resolve which mod this belongs to
        for root, mod_name in self.mod_map.items():
            if path.is_relative_to(root):
                rel_path = path.relative_to(root)
                # PUSH to DB - High Priority
                enqueue_file(
                    mod_name=mod_name, 
                    rel_path=str(rel_path), 
                    priority=PRIORITY_FLASH
                )
                logger.info(f"Detected change: {mod_name}/{rel_path}")
                break

class WatcherService:
    """Manages the watchdog observer thread."""
    
    def __init__(self, conn):
        self.conn = conn
        self.observer = Observer()
        self.active = False

    def start(self):
        # 1. Query DB for active mod roots to watch
        # We only watch what is currently indexed
        rows = self.conn.execute("""
            SELECT mp.name, mp.source_path 
            FROM mod_packages mp 
            JOIN content_versions cv ON mp.mod_package_id = cv.mod_package_id
            WHERE mp.source_path IS NOT NULL
        """).fetchall()

        mod_map = {Path(r['source_path']): r['name'] for r in rows}
        handler = ChangeHandler(mod_map)

        # 2. Schedule watches
        for path in mod_map.keys():
            if path.exists():
                self.observer.schedule(handler, str(path), recursive=True)
                logger.info(f"Watching: {path}")

        self.observer.start()
        self.active = True

    def stop(self):
        if self.active:
            self.observer.stop()
            self.observer.join()
            self.active = False
Step 3: Wire into qbuilder/cli.py
Update cmd_daemon to start the watcher alongside the IPC server.

Python
# qbuilder/cli.py

def cmd_daemon(args: argparse.Namespace) -> int:
    # ... existing setup ...
    from .watcher import WatcherService  # Import the new service
    
    try:
        # ... IPC Server start ...
        
        # --- NEW CODE START ---
        print("Starting filesystem watcher...")
        # Use a fresh connection for the watcher thread if needed, 
        # or pass the main one if it's strictly read-only setup
        watcher = WatcherService(get_connection()) 
        watcher.start()
        # --- NEW CODE END ---

        # ... Existing Worker Loop ...
        result = run_build_worker(...)

        # ... Shutdown sequence ...
        watcher.stop()  # Stop watcher on exit
        ipc_server.stop()
        
    finally:
        lock.release()
Step 4: Handle "Deletions" (The Missing Logic)
The agent noted that deletion detection was missing. watchdog has an on_deleted event. You need to map this to api.delete_file (which exists but wasn't wired).

Update ChangeHandler in watcher.py:

Python
    def on_deleted(self, event):
        if event.is_directory: return
        path = Path(event.src_path)
        
        for root, mod_name in self.mod_map.items():
            if path.is_relative_to(root):
                rel_path = path.relative_to(root)
                # Call the existing API
                from qbuilder.api import delete_file
                delete_file(mod_name, str(rel_path))
                logger.info(f"Detected deletion: {mod_name}/{rel_path}")
                break
This effectively closes the loop. The Daemon now has eyes (Watcher), a brain (DB/Queue), and hands (Worker).